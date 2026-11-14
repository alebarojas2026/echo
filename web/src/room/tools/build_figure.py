"""Builds the room's person figure, web/src/room/assets/person.glb, from nothing but this script.

    <python with the bpy module, 5.x> web/src/room/tools/build_figure.py [out.glb]

The figure is a smooth, faceless clay adult: 1.70 m tall, origin at the feet, facing +z in the glTF (-y in
Blender, z up). One skinned mesh with one material, no textures; soft ambient occlusion is baked into the vertex
colours. It carries a 19-bone rig and two clips: "walk" (an in-place loop, 32 frames at 30 fps) and "idle" (a calm
8 s standing loop). Every step is deterministic, so a rebuild gives the same file.

How it is made:
1. Shape. The body is a signed distance field: ellipsoids and round cones for the head, torso, limbs, hands and
   feet, joined with smooth unions so the joins read as one piece of clay. Surface nets turn the field into a
   dense mesh, and every vertex is pulled exactly onto the surface.
2. Topology. QuadriFlow remeshes that into about 1,450 even, mirror-symmetric quads (under 3,000 triangles), which
   are relaxed along the surface and pulled back onto it. Normals come from the field, so the shading is smooth.
3. Rig. Bone-heat weights, cleaned up: smoothed, kept to their own side, four influences per vertex.
4. Shading. Ambient occlusion from 128 rays per vertex, softened, stored in COLOR_0.
5. Motion. The walk is solved with leg IK from planted feet: each foot in stance moves backwards at exactly the
   walk speed (stride / cycle), heel strike, foot flat, heel rise and toe-off included, so the feet do not slide
   when the figure travels at that speed. The pelvis bobs, sways over the stance foot, turns and drops on the
   swing side; the chest turns against it and the arms swing opposite the legs. The idle is a breath every 4 s and
   one slow weight shift from foot to foot, with the feet planted.
6. Export, then a compaction pass: int8 normals (KHR_mesh_quantization), byte colours and weights, int16
   rotations, and keys that linear interpolation can rebuild are dropped.
"""

import json
import math
import os
import struct
import sys
import time

import bpy
import bmesh  # after bpy: bpy sets up the bmesh module
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'assets', 'person.glb'))

HEIGHT_M = 1.70
GRID_M = 0.005          # surface-nets cell size
QUADS = 1460            # QuadriFlow target (each quad is two triangles; the budget is 3,000)
MAX_TRIANGLES = 3000
FPS = 30
WALK_FRAMES = 32        # one cycle (two steps) = 32 / 30 = 1.067 s
STRIDE_M = 1.18         # ground covered per cycle at full stride
IDLE_FRAMES = 240       # 8 s
AMBER = (1.0, 0x9F / 255, 0x43 / 255)  # person #FF9F43 (sRGB); the app sets its own material from palette.ts

# ------------------------------------------------------------------------------------------------- proportions
# Joint centres for the LEFT side (+x), metres. Blender frame: x = the figure's left, -y = forward, z = up.
# Adult proportions, head about 1/7.5 of the height; arms rest about 11 degrees out from the body so they
# never fuse with the torso (the walk and idle bring them back in).
J = {
    'pelvis': (0.0, 0.004, 0.935),
    'waist': (0.0, 0.004, 1.075),
    'chest': (0.0, 0.006, 1.235),
    'neck': (0.0, 0.014, 1.425),
    'headbase': (0.0, 0.010, 1.510),
    'headtop': (0.0, 0.000, 1.700),
    'clav': (0.020, 0.004, 1.405),
    'shoulder': (0.160, 0.012, 1.383),
    'elbow': (0.214, 0.028, 1.105),
    'wrist': (0.252, 0.006, 0.862),
    'handtip': (0.269, -0.006, 0.690),
    'hip': (0.090, 0.004, 0.886),
    'knee': (0.096, -0.004, 0.490),
    'ankle': (0.100, 0.016, 0.086),
    'ball': (0.107, -0.112, 0.026),
    'toe': (0.112, -0.168, 0.024),
}
HEEL_BACK_M = 0.054     # the heel's contact point is this far behind the ankle


def side(name, s):
    """A left-side joint mirrored to side s (+1 left, -1 right)."""
    x, y, z = J[name]
    return (x * s, y, z)


# ------------------------------------------------------------------------------------------------- the clay field
def _len(v):
    return np.sqrt(np.einsum('ij,ij->i', v, v))


def sd_ellipsoid(p, c, r):
    q = (p - np.asarray(c)) / np.asarray(r)
    k0 = _len(q)
    k1 = _len(q / np.asarray(r))
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


def sd_oriented_ellipsoid(p, c, axes, r):
    q = (p - np.asarray(c)) @ np.asarray(axes).T
    return sd_ellipsoid(q, (0, 0, 0), r)


def sd_round_cone(p, a, b, r1, r2):
    """Exact distance to a cone with rounded ends: radius r1 at a, r2 at b (Inigo Quilez)."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    ba = b - a
    l2 = float(ba @ ba)
    rr = r1 - r2
    a2 = l2 - rr * rr
    il2 = 1.0 / l2
    pa = p - a
    y = pa @ ba
    z = y - l2
    xv = pa * l2 - np.outer(y, ba)
    x2 = np.einsum('ij,ij->i', xv, xv)
    y2 = y * y * l2
    z2 = z * z * l2
    k = math.copysign(1.0, rr) * rr * rr * x2 if rr != 0 else np.zeros_like(x2)
    d = (np.sqrt(np.maximum(x2 * a2 * il2, 0.0)) + y * rr) * il2 - r1
    end_b = np.sign(z) * a2 * z2 > k
    end_a = (np.sign(y) * a2 * y2 < k) & ~end_b
    d = np.where(end_b, np.sqrt(x2 + z2) * il2 - r2, d)
    return np.where(end_a, np.sqrt(x2 + y2) * il2 - r1, d)


def smin(a, b, k):
    h = np.maximum(k - np.abs(a - b), 0.0) / k
    return np.minimum(a, b) - h * h * k * 0.25


def smax(a, b, k):
    return -smin(-a, -b, k)


def _axes(a, b, side_hint):
    """An orthonormal frame whose first axis is side_hint (made perpendicular), second the a->b direction."""
    d = np.asarray(b, float) - np.asarray(a, float)
    d /= np.linalg.norm(d)
    u = np.asarray(side_hint, float)
    u = u - d * (u @ d)
    u /= np.linalg.norm(u)
    w = np.cross(u, d)
    return np.array([u, d, w])


def leg_sdf(p):
    """The left leg (thigh, knee, calf, shin, ankle, foot) at points p."""
    hip, knee, ankle = J['hip'], J['knee'], J['ankle']
    thigh = sd_round_cone(p, (hip[0], hip[1] + 0.004, hip[2] - 0.02), (knee[0], knee[1] + 0.002, knee[2] + 0.03), 0.073, 0.050)
    shin = sd_round_cone(p, (knee[0], knee[1] + 0.004, knee[2] - 0.01), (ankle[0], ankle[1] - 0.002, ankle[2] + 0.02), 0.047, 0.031)
    calf = sd_ellipsoid(p, (knee[0] + 0.002, 0.020, 0.355), (0.043, 0.047, 0.125))
    d = smin(thigh, shin, 0.05)
    d = smin(d, calf, 0.08)
    # The foot: a rounded wedge from heel to toe with a flat sole.
    foot = sd_round_cone(p, (ankle[0], ankle[1] + 0.030, 0.046), (J['toe'][0] - 0.004, J['toe'][1] + 0.022, 0.030), 0.046, 0.030)
    foot = smax(foot, -p[:, 2], 0.012)
    d = smin(d, foot, 0.035)
    return d


def arm_sdf(p):
    """The left arm and its mitten hand."""
    sh, el, wr, tip = J['shoulder'], J['elbow'], J['wrist'], J['handtip']
    upper = sd_round_cone(p, sh, el, 0.049, 0.037)
    fore = sd_round_cone(p, el, wr, 0.036, 0.025)
    belly = sd_round_cone(p, el, np.add(el, np.subtract(wr, el) * 0.45), 0.038, 0.031)
    d = smin(upper, fore, 0.025)
    d = smin(d, belly, 0.03)
    # A flat mitten, palm facing the thigh: thin across (x), wide front to back (y).
    hc = np.add(wr, np.subtract(tip, wr) * 0.46)
    hand = sd_oriented_ellipsoid(p, hc, _axes(wr, tip, (1, 0, 0)), (0.023, 0.086, 0.041))
    d = smin(d, hand, 0.022)
    return d


def torso_sdf(p):
    pelvis = sd_ellipsoid(p, (0, 0.024, 0.918), (0.134, 0.096, 0.118))
    glutes = sd_ellipsoid(p, (0, 0.032, 0.878), (0.120, 0.080, 0.090))
    belly = sd_ellipsoid(p, (0, 0.016, 1.080), (0.113, 0.082, 0.140))
    ribs = sd_ellipsoid(p, (0, 0.010, 1.262), (0.136, 0.098, 0.150))
    neck = sd_round_cone(p, (0, 0.020, 1.380), (0, 0.010, 1.515), 0.053, 0.046)
    d = smin(pelvis, glutes, 0.05)
    d = smin(d, belly, 0.10)
    d = smin(d, ribs, 0.08)
    d = smin(d, neck, 0.045)
    for s in (1.0, -1.0):
        # Shoulders slope from the neck to the arm, with a soft deltoid where the arm hangs.
        trap = sd_round_cone(p, (0, 0.018, 1.430), (0.138 * s, 0.014, 1.370), 0.041, 0.040)
        delt = sd_ellipsoid(p, (0.157 * s, 0.012, 1.350), (0.044, 0.046, 0.056))
        d = smin(d, trap, 0.05)
        d = smin(d, delt, 0.05)
    head = sd_ellipsoid(p, (0, -0.004, 1.600), (0.074, 0.089, 0.104))
    jaw = sd_ellipsoid(p, (0, -0.019, 1.552), (0.060, 0.066, 0.058))
    hd = smin(head, jaw, 0.05)
    return smin(d, hd, 0.035)


def body_sdf(p):
    p = np.asarray(p, dtype=np.float64)
    d = torso_sdf(p)
    for s in (1.0, -1.0):
        q = p * np.array([s, 1.0, 1.0])  # mirror the right side onto the left-side shapes
        d = smin(d, leg_sdf(q), 0.065)
    legs_done = d
    for s in (1.0, -1.0):
        q = p * np.array([s, 1.0, 1.0])
        legs_done = smin(legs_done, arm_sdf(q), 0.024)
    return legs_done


def sdf_grad(p, eps=1e-4):
    g = np.empty_like(p)
    for i in range(3):
        o = np.zeros(3)
        o[i] = eps
        g[:, i] = (body_sdf(p + o) - body_sdf(p - o)) / (2 * eps)
    return g


def project(p, iters=4):
    """Newton steps onto the zero level of the field."""
    for _ in range(iters):
        d = body_sdf(p)
        g = sdf_grad(p)
        p = p - (d / np.maximum(np.einsum('ij,ij->i', g, g), 1e-12))[:, None] * g
    return p


def unit_normals(p):
    g = sdf_grad(p)
    return g / np.maximum(_len(g), 1e-12)[:, None]


# ------------------------------------------------------------------------------------------------- surface nets
def surface_nets(lo, hi, h):
    nx, ny, nz = (np.ceil((np.asarray(hi) - np.asarray(lo)) / h).astype(int) + 1)
    xs = lo[0] + np.arange(nx) * h
    ys = lo[1] + np.arange(ny) * h
    zs = lo[2] + np.arange(nz) * h
    F = np.empty((nx, ny, nz), dtype=np.float32)
    X, Y = np.meshgrid(xs, ys, indexing='ij')
    for k, z in enumerate(zs):  # one slab at a time keeps the memory small
        pts = np.stack([X.ravel(), Y.ravel(), np.full(X.size, z)], axis=1)
        F[:, :, k] = body_sdf(pts).reshape(nx, ny)
    inside = F < 0
    corners = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 1)]
    cnt = np.zeros((nx - 1, ny - 1, nz - 1), dtype=np.int8)
    for (a, b, c) in corners:
        cnt += inside[a:nx - 1 + a, b:ny - 1 + b, c:nz - 1 + c]
    active = (cnt > 0) & (cnt < 8)
    ci = np.argwhere(active)
    index = -np.ones(active.shape, dtype=np.int64)
    index[tuple(ci.T)] = np.arange(len(ci))
    # Vertex per active cell: the mean of its edge crossings.
    edges = [((0, 0, 0), (1, 0, 0)), ((0, 1, 0), (1, 1, 0)), ((0, 0, 1), (1, 0, 1)), ((0, 1, 1), (1, 1, 1)),
             ((0, 0, 0), (0, 1, 0)), ((1, 0, 0), (1, 1, 0)), ((0, 0, 1), (0, 1, 1)), ((1, 0, 1), (1, 1, 1)),
             ((0, 0, 0), (0, 0, 1)), ((1, 0, 0), (1, 0, 1)), ((0, 1, 0), (0, 1, 1)), ((1, 1, 0), (1, 1, 1))]
    acc = np.zeros((len(ci), 3))
    num = np.zeros(len(ci))
    for e0, e1 in edges:
        i0 = ci + e0
        i1 = ci + e1
        f0 = F[tuple(i0.T)].astype(np.float64)
        f1 = F[tuple(i1.T)].astype(np.float64)
        m = (f0 < 0) != (f1 < 0)
        t = np.where(m, f0 / np.where(m, f0 - f1, 1.0), 0.0)
        pt = (i0 + t[:, None] * (np.asarray(e1) - np.asarray(e0))) * h + lo
        acc += pt * m[:, None]
        num += m
    verts = acc / np.maximum(num, 1)[:, None]
    # A quad around every grid edge whose ends differ in sign.
    quads = []
    for axis in range(3):
        a1, a2 = (axis + 1) % 3, (axis + 2) % 3
        sl0 = [slice(None)] * 3
        sl1 = [slice(None)] * 3
        sl0[axis] = slice(0, -1)
        sl1[axis] = slice(1, None)
        s0 = inside[tuple(sl0)]
        s1 = inside[tuple(sl1)]
        cross = np.argwhere(s0 != s1)
        ok = (cross[:, a1] > 0) & (cross[:, a2] > 0) & (cross[:, a1] < inside.shape[a1] - 1) & (cross[:, a2] < inside.shape[a2] - 1)
        cross = cross[ok]
        flip = s0[tuple(cross.T)]  # inside at the low end: the surface faces +axis

        def cell(d1, d2):
            c = cross.copy()
            c[:, a1] -= d1
            c[:, a2] -= d2
            return index[tuple(c.T)]

        q = np.stack([cell(1, 1), cell(0, 1), cell(0, 0), cell(1, 0)], axis=1)
        q[~flip] = q[~flip][:, ::-1]
        quads.append(q)
    return verts, np.concatenate(quads)


# ------------------------------------------------------------------------------------------------- Blender helpers
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = FPS


def activate(obj, *others):
    bpy.context.view_layer.update()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in others:
        o.select_set(True)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)


def mesh_arrays(me):
    v = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get('co', v)
    e = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get('vertices', e)
    return v.reshape(-1, 3), e.reshape(-1, 2)


def set_coords(me, p):
    me.vertices.foreach_set('co', p.astype(np.float32).ravel())
    me.update()


def tri_count(me):
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def neighbour_mean(values, edges, n):
    acc = np.zeros((n,) + values.shape[1:])
    deg = np.zeros(n)
    np.add.at(acc, edges[:, 0], values[edges[:, 1]])
    np.add.at(acc, edges[:, 1], values[edges[:, 0]])
    np.add.at(deg, edges[:, 0], 1)
    np.add.at(deg, edges[:, 1], 1)
    return acc / np.maximum(deg, 1).reshape((n,) + (1,) * (values.ndim - 1))


def mirror_partners(p, tol=0.004):
    kd = KDTree(len(p))
    for i, c in enumerate(p):
        kd.insert(c, i)
    kd.balance()
    partner = np.full(len(p), -1)
    for i, c in enumerate(p):
        co, j, dist = kd.find((-c[0], c[1], c[2]))
        if dist < tol:
            partner[i] = j
    return partner


def symmetrise(p, partner):
    q = p.copy()
    ok = partner >= 0
    m = p[partner[ok]] * np.array([-1.0, 1.0, 1.0])
    q[ok] = (p[ok] + m) * 0.5
    centre = ok & (partner == np.arange(len(p)))
    q[centre, 0] = 0.0
    return q


def relax(p, e, iters, partner=None):
    """Moves each vertex toward its neighbours' centre along the surface, then back onto it."""
    for _ in range(iters):
        n = unit_normals(p)
        delta = neighbour_mean(p, e, len(p)) - p
        delta -= n * np.einsum('ij,ij->i', delta, n)[:, None]
        p = project(p + 0.5 * delta, 2)
        if partner is not None:
            p = symmetrise(p, partner)
    return p


# ------------------------------------------------------------------------------------------------- 1-2. the mesh
def build_mesh():
    t0 = time.time()
    lo = np.array([-0.36, -0.26, -0.012])
    hi = np.array([0.36, 0.17, 1.735])
    verts, quads = surface_nets(lo, hi, GRID_M)
    me = bpy.data.meshes.new('person')
    me.from_pydata(verts.tolist(), [], quads.tolist())
    me.validate()
    obj = bpy.data.objects.new('person', me)
    bpy.context.scene.collection.objects.link(obj)
    # Surface nets can leave near-zero edges, which the remesher refuses: relax along the surface first.
    p, e = mesh_arrays(me)
    p = relax(p, e, 3)
    set_coords(me, p)
    short = np.linalg.norm(p[e[:, 0]] - p[e[:, 1]], axis=1).min()
    print(f'  surface nets: {len(p)} vertices, shortest edge {short * 1000:.2f} mm ({time.time() - t0:.1f} s)')

    # QuadriFlow lands near, not on, its target, and some runs come back open or drop a thin limb. Try a range of
    # targets and seeds; keep closed, all-quad results under the budget that stay on the clay surface (99.5 % of it
    # within 13 mm, all of it within 30 mm, so no limb is lost), and of those the most faithful. The symmetric remesh
    # returns two halves with duplicate vertices on x = 0, welded here.
    dense = obj.data
    probe = [Vector(c) for c in mesh_arrays(dense)[0][::15]]
    best, best_fit = None, None
    tried = []
    for target, seed in [(t, sd) for sd in (7, 11, 3) for t in range(QUADS - 300, QUADS + 40, 17)]:
        obj.data = dense.copy()
        obj.data.use_mirror_x = True
        activate(obj)
        bpy.ops.object.quadriflow_remesh(use_mesh_symmetry=True, use_preserve_sharp=False,
                                         use_preserve_boundary=False, preserve_attributes=False,
                                         smooth_normals=False, mode='FACES', target_faces=target, seed=seed)
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=[v for v in bm.verts if abs(v.co.x) < 1e-5], dist=1e-4)
        closed = all(ed.is_manifold for ed in bm.edges) and all(len(f.verts) == 4 for f in bm.faces)
        bvh = BVHTree.FromBMesh(bm)
        gaps = np.array([bvh.find_nearest(c)[3] for c in probe])
        bm.to_mesh(obj.data)
        bm.free()
        fit = np.percentile(gaps, 99.5)
        ok = closed and 2 * len(obj.data.polygons) <= MAX_TRIANGLES - 40 and fit < 0.013 and gaps.max() < 0.03
        tried.append(f"{len(obj.data.polygons)}{'' if closed else 'x'}:{fit * 1000:.0f}/{gaps.max() * 1000:.0f}")
        if ok and (best_fit is None or fit < best_fit):
            best, best_fit = obj.data, fit
    print('  candidates (quads[x = open]:p99.5/max mm):', ' '.join(tried))
    assert best is not None, 'no remesh was closed, under budget and on the surface'
    obj.data = best
    me = obj.data
    print(f'  quadriflow: {len(me.polygons)} quads, {tri_count(me)} triangles, closed, 99.5 % within '
          f'{best_fit * 1000:.1f} mm of the clay ({time.time() - t0:.1f} s)')

    # Even out the quads along the surface, pull them back onto it, and make the two halves exact mirrors.
    p, e = mesh_arrays(me)
    p = project(p, 4)
    partner = mirror_partners(p)
    p = relax(p, e, 6, partner)
    p = project(p, 3)
    p = symmetrise(p, partner)
    set_coords(me, p)
    unpaired = int((partner < 0).sum())
    print(f'  relaxed; {unpaired} vertices without a mirror partner')

    for poly in me.polygons:
        poly.use_smooth = True
    # Shading normals straight from the field: smooth clay even at this triangle count.
    n = unit_normals(p)
    me.normals_split_custom_set_from_vertices([tuple(v) for v in n])
    return obj


# ------------------------------------------------------------------------------------------------- 3. the rig
BONES = [  # name, head joint, tail joint, parent, roll axis (the bone's local z points this way)
    ('hips', 'pelvis', 'waist', None, (0, -1, 0)),
    ('spine', 'waist', 'chest', 'hips', (0, -1, 0)),
    ('chest', 'chest', 'neck', 'spine', (0, -1, 0)),
    ('neck', 'neck', 'headbase', 'chest', (0, -1, 0)),
    ('head', 'headbase', 'headtop', 'neck', (0, -1, 0)),
]
for _s in 'LR':
    BONES += [
        (f'clavicle.{_s}', f'clav.{_s}', f'shoulder.{_s}', 'chest', (0, 0, 1)),
        (f'upperarm.{_s}', f'shoulder.{_s}', f'elbow.{_s}', f'clavicle.{_s}', (0, -1, 0)),
        (f'forearm.{_s}', f'elbow.{_s}', f'handtip.{_s}', f'upperarm.{_s}', (0, -1, 0)),
        (f'thigh.{_s}', f'hip.{_s}', f'knee.{_s}', 'hips', (0, -1, 0)),
        (f'shin.{_s}', f'knee.{_s}', f'ankle.{_s}', f'thigh.{_s}', (0, -1, 0)),
        (f'foot.{_s}', f'ankle.{_s}', f'ball.{_s}', f'shin.{_s}', (0, 0, 1)),
        (f'toe.{_s}', f'ball.{_s}', f'toe.{_s}', f'foot.{_s}', (0, 0, 1)),
    ]


def joint(name):
    if name.endswith('.L') or name.endswith('.R'):
        return Vector(side(name[:-2], 1.0 if name.endswith('.L') else -1.0))
    return Vector(J[name])


def build_rig():
    arm = bpy.data.armatures.new('rig')
    rig = bpy.data.objects.new('rig', arm)
    bpy.context.scene.collection.objects.link(rig)
    activate(rig)
    bpy.ops.object.mode_set(mode='EDIT')
    for name, h, t, parent, roll in BONES:
        b = arm.edit_bones.new(name)
        b.head = joint(h)
        b.tail = joint(t)
        b.align_roll(Vector(roll))
    for name, h, t, parent, roll in BONES:
        if parent:
            arm.edit_bones[name].parent = arm.edit_bones[parent]
            arm.edit_bones[name].use_connect = False
    bpy.ops.object.mode_set(mode='OBJECT')
    return rig


def bind(obj, rig):
    """Bone-heat weights, then: keep each side's bones on its own side, smooth, four influences, normalised."""
    activate(rig, obj)
    bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    names = [b[0] for b in BONES]
    me = obj.data
    nv = len(me.vertices)
    W = np.zeros((nv, len(names)))
    gi = {g.index: names.index(g.name) for g in obj.vertex_groups if g.name in names}
    for v in me.vertices:
        for g in v.groups:
            if g.group in gi:
                W[v.index, gi[g.group]] = g.weight
    p, e = mesh_arrays(me)
    missing = int((W.sum(1) < 1e-6).sum())
    side_l = np.array([n.endswith('.L') for n in names])
    side_r = np.array([n.endswith('.R') for n in names])
    for _ in range(2):
        W = 0.6 * W + 0.4 * neighbour_mean(W, e, nv)
        W[p[:, 0] < -0.012][:, side_l] = 0
        W[np.ix_(p[:, 0] < -0.012, side_l)] = 0
        W[np.ix_(p[:, 0] > 0.012, side_r)] = 0
    # Four influences, normalised.
    order = np.argsort(-W, axis=1)
    keep = np.zeros_like(W, dtype=bool)
    np.put_along_axis(keep, order[:, :4], True, axis=1)
    W = np.where(keep, W, 0.0)
    W[W < 0.01] = 0
    W /= np.maximum(W.sum(1, keepdims=True), 1e-9)
    for g in list(obj.vertex_groups):
        obj.vertex_groups.remove(g)
    groups = [obj.vertex_groups.new(name=n) for n in names]
    for i in range(nv):
        for j in np.nonzero(W[i])[0]:
            groups[j].add([i], float(W[i, j]), 'REPLACE')
    print(f'  weights: {missing} vertices had no bone-heat weight before smoothing; '
          f'max influences {int((W > 0).sum(1).max())}')
    return W


# ------------------------------------------------------------------------------------------------- 4. occlusion
def bake_ao(obj, rays=128, reach=0.32, strength=0.7):
    me = obj.data
    p, e = mesh_arrays(me)
    n = unit_normals(p)
    polys = [tuple(poly.vertices) for poly in me.polygons]
    bvh = BVHTree.FromPolygons([tuple(c) for c in p], polys)
    # Cosine-weighted hemisphere directions (a fixed Fibonacci set, so the bake is repeatable).
    k = np.arange(rays) + 0.5
    r = np.sqrt(k / rays)
    th = k * math.pi * (3 - math.sqrt(5))
    local = np.stack([r * np.cos(th), r * np.sin(th), np.sqrt(1 - r * r)], axis=1)
    occ = np.zeros(len(p))
    for i in range(len(p)):
        nz = n[i]
        tx = np.cross(nz, (1.0, 0.0, 0.0) if abs(nz[0]) < 0.9 else (0.0, 1.0, 0.0))
        tx /= np.linalg.norm(tx)
        ty = np.cross(nz, tx)
        dirs = local[:, :1] * tx + local[:, 1:2] * ty + local[:, 2:] * nz
        origin = Vector(p[i] + nz * 0.0015)
        hit = 0.0
        for d in dirs:
            loc, _, _, dist = bvh.ray_cast(origin, Vector(d), reach)
            if loc is not None:
                hit += 1.0 - dist / reach  # near surfaces darken more: a soft falloff
        occ[i] = hit / rays
    for _ in range(3):
        occ = 0.5 * occ + 0.5 * neighbour_mean(occ, e, len(p))
    shade = np.clip(1.0 - strength * np.clip(occ * 2.5, 0, 1) ** 0.9, 0.35, 1.0)
    attr = me.color_attributes.new('ao', 'FLOAT_COLOR', 'POINT')
    cols = np.stack([shade, shade, shade, np.ones_like(shade)], axis=1)
    attr.data.foreach_set('color', cols.astype(np.float32).ravel())
    me.color_attributes.active_color = attr
    me.color_attributes.render_color_index = me.color_attributes.active_color_index
    print(f'  ao: shade {shade.min():.2f}..{shade.max():.2f}, mean {shade.mean():.2f}')
    return shade


# ------------------------------------------------------------------------------------------------- 5. motion
def rot_x(a):
    return Matrix.Rotation(a, 3, 'X')


def rot_y(a):
    return Matrix.Rotation(a, 3, 'Y')


def rot_z(a):
    return Matrix.Rotation(a, 3, 'Z')


def smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def hermite(p0, m0, p1, m1, t):
    t2, t3 = t * t, t * t * t
    return (2 * t3 - 3 * t2 + 1) * p0 + (t3 - 2 * t2 + t) * m0 + (-2 * t3 + 3 * t2) * p1 + (t3 - t2) * m1


def frame_of(y, h):
    """Columns (h, y, h x y): a bone frame from its direction y and its hinge axis h."""
    y = y.normalized()
    h = (h - y * h.dot(y)).normalized()
    return Matrix((h, y, h.cross(y))).transposed()


class Kinematics:
    """Forward kinematics over the rest skeleton: pose matrices in armature space from per-bone world turns."""

    def __init__(self, rig):
        self.rest = {b.name: b.matrix_local.copy() for b in rig.data.bones}
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in rig.data.bones}
        self.head = {b.name: b.head_local.copy() for b in rig.data.bones}
        self.tail = {b.name: b.tail_local.copy() for b in rig.data.bones}
        self.order = [b[0] for b in BONES]

    def length(self, name):
        return (self.tail[name] - self.head[name]).length

    def pose(self, turns, root_offset):
        """turns: bone -> 3x3 world rotation applied to its rest orientation. Returns bone -> 4x4 pose matrix."""
        P = {}
        for name in self.order:
            R = turns.get(name, Matrix.Identity(3)) @ self.rest[name].to_3x3()
            par = self.parent[name]
            if par is None:
                head = self.head[name] + root_offset
            else:
                head = P[par] @ (self.rest[par].inverted() @ self.head[name])
            M = R.to_4x4()
            M.translation = head
            P[name] = M
        return P

    def joint_pos(self, P, name, point):
        """Where a rest-pose point carried by bone `name` sits in pose P."""
        return P[name] @ (self.rest[name].inverted() @ point)

    def basis(self, P):
        out = {}
        for name in self.order:
            par = self.parent[name]
            if par is None:
                B = self.rest[name].inverted() @ P[name]
            else:
                B = (self.rest[par].inverted() @ self.rest[name]).inverted() @ P[par].inverted() @ P[name]
            loc, rot, _ = B.decompose()
            out[name] = (loc, rot)
        return out


def two_bone(H, A, pole, L1, L2):
    """Knee (or elbow) position for a chain H -> K -> A with segment lengths L1, L2, bending toward pole."""
    d = A - H
    dist = d.length
    reach = (L1 + L2) * 0.99999
    over = max(0.0, dist - reach)
    dist = min(dist, reach)
    u = d.normalized()
    w = (pole - u * pole.dot(u)).normalized()
    ca = (L1 * L1 + dist * dist - L2 * L2) / (2 * L1 * dist)
    sa = math.sqrt(max(0.0, 1 - ca * ca))
    return H + (u * ca + w * sa) * L1, u, w, over


class Leg:
    def __init__(self, kin, s):
        self.s = s
        tag = 'L' if s > 0 else 'R'
        self.thigh, self.shin, self.foot, self.toe = (f'thigh.{tag}', f'shin.{tag}', f'foot.{tag}', f'toe.{tag}')
        self.L1 = kin.length(self.thigh)
        self.L2 = kin.length(self.shin)
        self.hip0 = kin.head[self.thigh]
        self.knee0 = kin.head[self.shin]
        self.ankle0 = kin.head[self.foot]
        self.ball0 = kin.head[self.toe]
        self.toe0 = kin.tail[self.toe]
        self.heel_v = Vector((0, HEEL_BACK_M, -self.ankle0.z))            # ankle -> heel contact
        self.ball_v = Vector((self.ball0.x - self.ankle0.x, self.ball0.y - self.ankle0.y, -self.ankle0.z))
        self.toe_v = self.toe0 - self.ankle0
        u0 = (self.ankle0 - self.hip0).normalized()
        self.hinge0 = u0.cross((Vector((0, -1, 0)) - u0 * u0.dot(Vector((0, -1, 0)))).normalized())
        self.y_thigh0 = (self.knee0 - self.hip0).normalized()
        self.y_shin0 = (self.ankle0 - self.knee0).normalized()

    def solve(self, kin, P, ankle, foot_turn, toe_turn, pole):
        """Adds thigh, shin, foot and toe turns for an ankle target. Returns (turns, overreach in m)."""
        H = kin.joint_pos(P, 'hips', self.hip0)
        K, u, w, over = two_bone(H, ankle, pole, self.L1, self.L2)
        A = H + (ankle - H).normalized() * min((ankle - H).length, (self.L1 + self.L2) * 0.99999)
        h = u.cross(w).normalized()
        turns = {
            self.thigh: frame_of(K - H, h) @ frame_of(self.y_thigh0, self.hinge0).transposed(),
            self.shin: frame_of(A - K, h) @ frame_of(self.y_shin0, self.hinge0).transposed(),
            self.foot: foot_turn,
            self.toe: toe_turn,
        }
        return turns, over


# Walk tuning. Angles in degrees; the phase runs 0..1 over one cycle, the right heel strikes at 0.
TOE_OFF = 0.62          # stance ends (62 % of the cycle, double support 12 % twice)
FOOT_FLAT = 0.10        # heel rocker ends
HEEL_RISE = 0.36        # heel starts to rise
HEEL_STRIKE_DEG = 15.0  # toes up at heel strike
TOE_OFF_DEG = 36.0      # foot pitched down at toe-off
TRACK_X = 0.082         # feet land this far either side of the midline
SWAY_M = 0.020          # pelvis over the stance foot
BOB_M = 0.019           # half the vertical travel
YAW_DEG = 5.0           # pelvis turn (leading hip forward)
ROLL_DEG = 3.2          # swing-side hip drop
CHEST_YAW_DEG = 4.5     # shoulders turn against the pelvis
LEAN_DEG = 3.0          # trunk forward lean while walking
ARM_SWING_DEG = 17.0
ARM_FORWARD_DEG = -5.0  # arms swing further back than forward
ELBOW_DEG = 12.0        # relaxed elbow bend, more on the forward swing
ELBOW_SWING_DEG = 14.0
ADDUCT_DEG = 7.5        # arms in from the rest pose's 11 degrees
KNEE_MIN_DEG = 5.0      # the stance knee never locks straight


def foot_plan(leg, u, stride):
    """Ankle position, foot turn and toe turn for a foot at gait phase u (0 = its heel strike)."""
    s = leg.s
    x = s * TRACK_X
    heel0_y = -0.30          # heel strike point, forward of the hips (y < 0 is forward)
    deg = math.radians

    def heel_contact(uu):
        return Vector((x, heel0_y + stride * uu, 0.0))

    def stance(uu):
        if uu < FOOT_FLAT:
            th = deg(HEEL_STRIKE_DEG) * (1 - smooth(uu / FOOT_FLAT))
            R = rot_x(-th)
            ankle = heel_contact(uu) - R @ leg.heel_v
            return ankle, R, R
        if uu < HEEL_RISE:
            ankle = heel_contact(uu) - leg.heel_v
            return ankle, Matrix.Identity(3), Matrix.Identity(3)
        th = -deg(TOE_OFF_DEG) * smooth((uu - HEEL_RISE) / (TOE_OFF - HEEL_RISE))
        R = rot_x(-th)
        ball = heel_contact(uu) + (leg.ball_v - leg.heel_v)
        ball.z = 0.0
        ankle = ball - R @ leg.ball_v
        return ankle, R, Matrix.Identity(3)

    if u < TOE_OFF:
        return stance(u) + (True,)
    # Swing: a Hermite curve from the toe-off state to the next heel strike, matching both ends' velocity.
    e = 1e-4
    a0, _, _ = stance(TOE_OFF - e)
    a0m, _, _ = stance(TOE_OFF - 2 * e)
    a1, _, _ = stance(0.0)
    a1p, _, _ = stance(e)
    span = 1 - TOE_OFF
    v0 = (a0 - a0m) / e * span
    v1 = (a1p - a1) / e * span
    t = (u - TOE_OFF) / span
    ankle = hermite(a0, v0, a1, v1, t)
    ankle.z += 0.055 * math.sin(math.pi * t) ** 2 * (1.15 - 0.3 * t)  # clearance: the foot lifts, then reaches
    th = -deg(TOE_OFF_DEG) + (deg(HEEL_STRIKE_DEG) + deg(TOE_OFF_DEG)) * smooth(t / 0.72)
    R = rot_x(-th)
    toe_bend = deg(TOE_OFF_DEG) * (1 - smooth(t / 0.35))
    return ankle, R, rot_x(-(th + toe_bend)), False


def pelvis_turn(yaw, roll, lean):
    return rot_z(yaw) @ rot_y(roll) @ rot_x(lean)


def walk_pose(kin, legs, phase, z0, stride):
    deg = math.radians
    tau = 2 * math.pi
    sway = -SWAY_M * math.sin(tau * (phase - 0.06))
    bob = BOB_M * math.cos(2 * tau * (phase - 0.31))
    yaw = deg(YAW_DEG) * math.cos(tau * phase)
    roll = deg(ROLL_DEG) * math.sin(tau * (phase - 0.06))
    lean = deg(LEAN_DEG)
    chest_yaw = -deg(CHEST_YAW_DEG) * math.cos(tau * (phase - 0.02))
    turns = {
        'hips': pelvis_turn(yaw, roll, lean * 0.4),
        'spine': pelvis_turn(yaw * 0.35 + chest_yaw * 0.3, -roll * 0.35, lean * 0.8),
        'chest': pelvis_turn(chest_yaw, -roll * 0.15, lean),
        'head': pelvis_turn(chest_yaw * 0.25, 0.0, lean * 0.15),
    }
    turns['neck'] = turns['chest'].to_quaternion().slerp(turns['head'].to_quaternion(), 0.5).to_matrix()
    for s in (1.0, -1.0):
        tag = 'L' if s > 0 else 'R'
        # The arm swings with the opposite leg: the right arm is furthest forward at the left heel strike (0.5).
        peak = 0.53 if s < 0 else 0.03
        c = math.cos(tau * (phase - peak))
        swing = deg(ARM_FORWARD_DEG) + deg(ARM_SWING_DEG) * c
        elbow = deg(ELBOW_DEG) + deg(ELBOW_SWING_DEG) * 0.5 * (1 + c)
        cy = rot_z(chest_yaw)
        turns[f'clavicle.{tag}'] = cy @ rot_z(-s * 0.12 * swing) @ rot_y(-s * deg(1.0))
        turns[f'upperarm.{tag}'] = cy @ rot_x(-swing) @ rot_y(s * deg(ADDUCT_DEG))
        turns[f'forearm.{tag}'] = cy @ rot_x(-(swing + elbow)) @ rot_y(s * deg(ADDUCT_DEG - 2.0))
    root = Vector((sway, 0.0, z0 + bob - kin.head['hips'].z))
    P = kin.pose(turns, root)
    over = 0.0
    for leg in legs:
        u = (phase + (0.0 if leg.s < 0 else 0.5)) % 1.0
        ankle, foot_turn, toe_turn, _ = foot_plan(leg, u, stride)
        pole = rot_z(yaw) @ Vector((leg.s * 0.12, -1.0, 0.0))
        lt, o = leg.solve(kin, P, ankle, foot_turn, toe_turn, pole)
        turns.update(lt)
        over = max(over, o)
    return kin.pose(turns, root), over


def stance_reach_ok(kin, legs, phase, z0, stride):
    """True when every planted leg reaches its ankle with the knee bent at least KNEE_MIN_DEG."""
    L1, L2 = legs[0].L1, legs[0].L2
    dmax = math.sqrt(L1 * L1 + L2 * L2 + 2 * L1 * L2 * math.cos(math.radians(KNEE_MIN_DEG)))
    P, _ = walk_pose(kin, legs, phase, z0, stride)
    for leg in legs:
        u = (phase + (0.0 if leg.s < 0 else 0.5)) % 1.0
        ankle, _, _, planted = foot_plan(leg, u, stride)
        if planted and (ankle - kin.joint_pos(P, 'hips', leg.hip0)).length > dmax:
            return False
    return True


def walk_height(kin, legs, stride):
    """The highest pelvis line (plus the bob) that keeps every planted knee a little bent all cycle."""
    lo, hi = 0.70, 1.0
    phases = [i / 64 for i in range(64)]
    for _ in range(22):
        mid = (lo + hi) / 2
        if all(stance_reach_ok(kin, legs, ph, mid, stride) for ph in phases):
            lo = mid
        else:
            hi = mid
    return lo


def idle_pose(kin, legs, tau_, z0):
    deg = math.radians
    tau = 2 * math.pi
    shift = math.sin(tau * tau_)                 # one slow weight shift, left then right, per 8 s
    breath = math.sin(2 * tau * tau_)             # a breath every 4 s
    sway = 0.011 * shift
    roll = -deg(1.3) * shift                       # the unloaded hip drops a little
    yaw = deg(0.6) * math.sin(tau * tau_ + 0.8)
    turns = {
        'hips': pelvis_turn(yaw, roll, 0.0),
        'spine': pelvis_turn(yaw * 0.3, -roll * 0.6, -deg(0.25) * breath),
        'chest': pelvis_turn(-yaw * 0.2, -roll * 0.3, -deg(0.55) * breath),
        'head': pelvis_turn(-yaw * 0.3, -roll * 0.1, deg(0.2) * breath),
    }
    turns['neck'] = turns['chest'].to_quaternion().slerp(turns['head'].to_quaternion(), 0.5).to_matrix()
    for s in (1.0, -1.0):
        tag = 'L' if s > 0 else 'R'
        swing = deg(1.0) + deg(0.35) * breath + deg(0.4) * s * shift
        turns[f'clavicle.{tag}'] = rot_y(-s * deg(1.0 + 0.7 * (0.5 + 0.5 * breath)))
        turns[f'upperarm.{tag}'] = rot_x(-swing) @ rot_y(s * deg(ADDUCT_DEG + 0.5))
        turns[f'forearm.{tag}'] = rot_x(-(swing + deg(9.0))) @ rot_y(s * deg(ADDUCT_DEG - 1.5))
    root = Vector((sway, 0.0, z0 - kin.head['hips'].z))
    P = kin.pose(turns, root)
    for leg in legs:
        ankle = leg.ankle0.copy()
        pole = Vector((leg.s * 0.1, -1.0, 0.0))
        lt, _ = leg.solve(kin, P, ankle, Matrix.Identity(3), Matrix.Identity(3), pole)
        turns.update(lt)
    return kin.pose(turns, root)


def idle_height(kin, legs):
    L1, L2 = legs[0].L1, legs[0].L2
    dmax = math.sqrt(L1 * L1 + L2 * L2 + 2 * L1 * L2 * math.cos(math.radians(3.0)))
    lo, hi = 0.80, 1.0
    for _ in range(22):
        mid = (lo + hi) / 2
        ok = True
        for i in range(32):
            P = idle_pose(kin, legs, i / 32, mid)
            for leg in legs:
                if (leg.ankle0 - kin.joint_pos(P, 'hips', leg.hip0)).length > dmax:
                    ok = False
        lo, hi = (mid, hi) if ok else (lo, mid)
    return lo


def key_action(rig, kin, name, poses):
    act = bpy.data.actions.new(name)
    rig.animation_data_create()
    rig.animation_data.action = act
    prev = {}
    for f, P in enumerate(poses):
        basis = kin.basis(P)
        for bname, (loc, rot) in basis.items():
            pb = rig.pose.bones[bname]
            pb.rotation_mode = 'QUATERNION'
            q = Quaternion(rot)
            if bname in prev and prev[bname].dot(q) < 0:
                q.negate()
            prev[bname] = q
            pb.rotation_quaternion = q
            pb.keyframe_insert('rotation_quaternion', frame=f, group=bname)
            if bname == 'hips':
                pb.location = loc
                pb.keyframe_insert('location', frame=f, group=bname)
    slot = rig.animation_data.action_slot
    rig.animation_data.action = None
    track = rig.animation_data.nla_tracks.new()
    track.name = name
    strip = track.strips.new(name, 0, act)
    strip.action_slot = slot
    act.use_fake_user = True
    return act


def animate(rig):
    kin = Kinematics(rig)
    legs = [Leg(kin, 1.0), Leg(kin, -1.0)]
    z_walk = walk_height(kin, legs, STRIDE_M)
    walk, over = [], 0.0
    for f in range(WALK_FRAMES + 1):
        P, o = walk_pose(kin, legs, (f % WALK_FRAMES) / WALK_FRAMES, z_walk, STRIDE_M)
        walk.append(P)
        over = max(over, o)
    z_idle = idle_height(kin, legs)
    idle = [idle_pose(kin, legs, (f % IDLE_FRAMES) / IDLE_FRAMES, z_idle) for f in range(IDLE_FRAMES + 1)]
    key_action(rig, kin, 'walk', walk)
    key_action(rig, kin, 'idle', idle)
    rest_hip = kin.head['hips'].z
    print(f'  walk: pelvis {z_walk - BOB_M:.3f}..{z_walk + BOB_M:.3f} m (rest {rest_hip:.3f}), '
          f'swing overreach {over * 1000:.1f} mm; idle pelvis {z_idle:.3f} m')
    return legs


def check_feet(obj, rig, legs):
    """Measures foot slide on the skinned mesh: the planted sole's lowest vertices should move backwards at exactly
    stride / cycle. Returns the worst deviation in mm/s."""
    deps = bpy.context.evaluated_depsgraph_get()
    ad = rig.animation_data
    strip = ad.nla_tracks['walk'].strips[0]
    for t in ad.nla_tracks:
        t.mute = True
    ad.action = strip.action
    ad.action_slot = strip.action_slot
    rows = []
    for f in range(WALK_FRAMES + 1):
        bpy.context.scene.frame_set(f)
        ev = obj.evaluated_get(deps)
        m = ev.to_mesh()
        co = np.empty(len(m.vertices) * 3)
        m.vertices.foreach_get('co', co)
        ev.to_mesh_clear()
        rows.append(co.reshape(-1, 3))
    ad.action = None
    for t in ad.nla_tracks:
        t.mute = False
    bpy.context.scene.frame_set(0)
    co = np.stack(rows)  # frames x verts x 3
    v_expected = STRIDE_M / (WALK_FRAMES / FPS)
    worst = 0.0
    for leg in legs:
        sel = (co[0, :, 0] * leg.s > 0.04) & (co[0, :, 2] < 0.2)
        for f in range(WALK_FRAMES):
            u = ((f / WALK_FRAMES) + (0.0 if leg.s < 0 else 0.5)) % 1.0
            if not (FOOT_FLAT + 0.02 < u < HEEL_RISE - 0.02):
                continue
            low = sel & (co[f, :, 2] < 0.012) & (co[f + 1, :, 2] < 0.012)
            if low.sum() < 3:
                continue
            vy = (co[f + 1, low, 1] - co[f, low, 1]).mean() * FPS
            worst = max(worst, abs(vy - v_expected))
    print(f'  foot check: planted sole moves back at {v_expected:.3f} m/s; worst deviation {worst * 1000:.1f} mm/s')
    return worst


# ------------------------------------------------------------------------------------------------- 6. export
def material():
    """One plain amber material (the app swaps in its own clay shader; this is for other glTF viewers)."""
    mat = bpy.data.materials.new('person')
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in AMBER]
    mat.diffuse_color = (*lin, 1.0)
    bsdf = mat.node_tree.nodes.get('Principled BSDF') if mat.node_tree else None
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (*lin, 1.0)
        bsdf.inputs['Roughness'].default_value = 1.0
    return mat


def export(obj, rig, path):
    obj.data.materials.clear()
    obj.data.materials.append(material())
    activate(rig, obj)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=path, export_format='GLB', use_selection=True, export_yup=True, export_apply=False,
        export_texcoords=False, export_normals=True, export_tangents=False, export_materials='EXPORT',
        export_vertex_color='ACTIVE', export_all_vertex_colors=False, export_attributes=False,
        export_skins=True, export_influence_nb=4, export_all_influences=False, export_def_bones=True,
        export_animations=True, export_animation_mode='ACTIONS', export_force_sampling=True, export_frame_step=1,
        export_optimize_animation_size=True, export_anim_single_armature=True, export_reset_pose_bones=True,
        export_rest_position_armature=True, export_morph=False, export_extras=False, export_cameras=False,
        export_lights=False,
    )


# ------------------------------------------------------------------------------------------------- compaction
COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def read_glb(path):
    data = open(path, 'rb').read()
    magic, _, _ = struct.unpack_from('<III', data, 0)
    assert magic == 0x46546C67
    jlen, _ = struct.unpack_from('<II', data, 12)
    doc = json.loads(data[20:20 + jlen])
    off = 20 + jlen
    blen, _ = struct.unpack_from('<II', data, off)
    return doc, data[off + 8:off + 8 + blen]


def accessor_array(doc, binary, i):
    a = doc['accessors'][i]
    bv = doc['bufferViews'][a['bufferView']]
    dt = np.dtype(COMP[a['componentType']])
    n = NCOMP[a['type']]
    stride = bv.get('byteStride', dt.itemsize * n)
    start = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    raw = np.frombuffer(binary, dtype=np.uint8, count=stride * (a['count'] - 1) + dt.itemsize * n, offset=start)
    out = np.lib.stride_tricks.as_strided(raw, shape=(a['count'], n * dt.itemsize), strides=(stride, 1))
    return np.ascontiguousarray(out).view(dt).reshape(a['count'], n)


def decimate(times, values, tol):
    """Indices of the keys to keep so that linear interpolation stays within tol of every dropped key."""
    keep = [0]
    i = 0
    n = len(times)
    while i < n - 1:
        j = i + 2
        while j < n:
            t = (times[i + 1:j] - times[i]) / (times[j] - times[i])
            approx = values[i] + (values[j] - values[i]) * t[:, None]
            if np.abs(approx - values[i + 1:j]).max() > tol:
                break
            j += 1
        i = j - 1
        keep.append(i)
    return np.array(keep)


def compact(path, extras):
    doc, binary = read_glb(path)
    arrays = {}   # accessor index -> (array, componentType, normalized, target)
    prim = doc['meshes'][0]['primitives'][0]
    attrs = prim['attributes']
    for i in range(len(doc['accessors'])):
        a = doc['accessors'][i]
        arrays[i] = [accessor_array(doc, binary, i), a['componentType'], a.get('normalized', False), None]
    for name, i in attrs.items():
        arrays[i][3] = 34962
    arrays[prim['indices']][3] = 34963
    # Normals: int8, normalised (KHR_mesh_quantization).
    nrm = arrays[attrs['NORMAL']][0].astype(np.float64)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    arrays[attrs['NORMAL']][:3] = [np.round(nrm * 127).astype(np.int8), 5120, True]
    # Occlusion colour: one byte per channel, rgb only.
    col = arrays[attrs['COLOR_0']][0]
    if col.dtype != np.float32:
        col = col.astype(np.float64) / np.iinfo(col.dtype).max
    arrays[attrs['COLOR_0']][:3] = [np.round(np.clip(col[:, :3], 0, 1) * 255).astype(np.uint8), 5121, True]
    # Weights: bytes that sum to exactly 255.
    w = arrays[attrs['WEIGHTS_0']][0].astype(np.float64)
    w /= np.maximum(w.sum(1, keepdims=True), 1e-9)
    wq = np.floor(w * 255).astype(np.int64)
    rest = 255 - wq.sum(1)
    order = np.argsort(-(w * 255 - wq), axis=1)
    for r in range(4):
        add = rest > r
        wq[np.arange(len(wq))[add], order[add, r]] += 1
    arrays[attrs['WEIGHTS_0']][:3] = [wq.astype(np.uint8), 5121, True]
    # Animation: drop keys linear interpolation can rebuild, and store rotations as normalised int16.
    new_samplers = 0
    for anim in doc['animations']:
        # The exporter adds two-key STEP tracks for unanimated translation and scale; they only repeat the rest
        # pose, which the player falls back to anyway.
        kept = []
        for ch in anim['channels']:
            smp = anim['samplers'][ch['sampler']]
            if smp.get('interpolation', 'LINEAR') == 'STEP':
                v = arrays[smp['output']][0]
                assert np.allclose(v, v[0], atol=1e-6), 'a STEP track that moves'
                continue
            kept.append(ch)
        samplers = []
        for ch in kept:
            samplers.append(anim['samplers'][ch['sampler']])
            ch['sampler'] = len(samplers) - 1
        anim['channels'], anim['samplers'] = kept, samplers
        for ch in anim['channels']:
            smp = anim['samplers'][ch['sampler']]
            assert smp.get('interpolation', 'LINEAR') == 'LINEAR'
            t = arrays[smp['input']][0][:, 0].astype(np.float64)
            v = arrays[smp['output']][0].astype(np.float64)
            path_ = ch['target']['path']
            tol = 0.0004 if path_ == 'rotation' else 0.0002
            if path_ == 'rotation':
                for k in range(1, len(v)):
                    if v[k] @ v[k - 1] < 0:
                        v[k] = -v[k]
            keep = decimate(t, v, tol)
            ti = len(arrays)
            arrays[ti] = [t[keep].astype(np.float32).reshape(-1, 1), 5126, False, None]
            oi = len(arrays)
            if path_ == 'rotation':
                q = v[keep] / np.linalg.norm(v[keep], axis=1, keepdims=True)
                arrays[oi] = [np.round(q * 32767).astype(np.int16), 5122, True, None]
            else:
                arrays[oi] = [v[keep].astype(np.float32), 5126, False, None]
            smp['input'], smp['output'] = ti, oi
            new_samplers += 1
    # Rebuild every accessor and buffer view from the arrays still in use.
    used = set(attrs.values()) | {prim['indices']}
    for sk in doc.get('skins', []):
        used.add(sk['inverseBindMatrices'])
    for anim in doc['animations']:
        for smp in anim['samplers']:
            used |= {smp['input'], smp['output']}
    remap, accessors, views, blob = {}, [], [], bytearray()
    for old in sorted(used):
        arr, ctype, normd, target = arrays[old]
        n = arr.shape[1]
        elem = arr.dtype.itemsize * n
        stride = (elem + 3) // 4 * 4 if target == 34962 else elem
        rows = np.zeros((len(arr), stride), dtype=np.uint8)
        rows[:, :elem] = np.ascontiguousarray(arr).view(np.uint8).reshape(len(arr), elem)
        while len(blob) % 4:
            blob.append(0)
        view = {'buffer': 0, 'byteOffset': len(blob), 'byteLength': rows.size}
        if target == 34962:
            view['target'] = target
            if stride != elem:
                view['byteStride'] = stride
        elif target == 34963:
            view['target'] = target
        blob += rows.tobytes() if target != 34963 else arr.tobytes()
        if target == 34963:
            view['byteLength'] = arr.nbytes
        acc = {'bufferView': len(views), 'componentType': ctype, 'count': len(arr),
               'type': {1: 'SCALAR', 2: 'VEC2', 3: 'VEC3', 4: 'VEC4', 16: 'MAT4'}[n]}
        if normd:
            acc['normalized'] = True
        is_input = any(smp['input'] == old for an in doc['animations'] for smp in an['samplers'])
        if old == attrs['POSITION'] or is_input:
            acc['min'] = [float(x) for x in arr.min(0)]
            acc['max'] = [float(x) for x in arr.max(0)]
        remap[old] = len(accessors)
        accessors.append(acc)
        views.append(view)
    for k in list(attrs):
        attrs[k] = remap[attrs[k]]
    prim['indices'] = remap[prim['indices']]
    for sk in doc.get('skins', []):
        sk['inverseBindMatrices'] = remap[sk['inverseBindMatrices']]
    for anim in doc['animations']:
        for smp in anim['samplers']:
            smp['input'], smp['output'] = remap[smp['input']], remap[smp['output']]
    while len(blob) % 4:
        blob.append(0)
    doc['accessors'], doc['bufferViews'] = accessors, views
    doc['buffers'] = [{'byteLength': len(blob)}]
    doc['extensionsUsed'] = sorted(set(doc.get('extensionsUsed', [])) | {'KHR_mesh_quantization'})
    doc['extensionsRequired'] = sorted(set(doc.get('extensionsRequired', [])) | {'KHR_mesh_quantization'})
    doc['scenes'][doc.get('scene', 0)]['extras'] = extras
    doc['asset']['generator'] = 'web/src/room/tools/build_figure.py'
    js = json.dumps(doc, separators=(',', ':')).encode()
    js += b' ' * (-len(js) % 4)
    out = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob))
    out += struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(blob), 0x004E4942) + bytes(blob)
    open(path, 'wb').write(out)
    return doc


# ------------------------------------------------------------------------------------------------- main
def main():
    t0 = time.time()
    reset()
    print('[figure] shape and topology')
    obj = build_mesh()
    tris = tri_count(obj.data)
    assert tris <= MAX_TRIANGLES, f'{tris} triangles is over the {MAX_TRIANGLES} budget'
    print('[figure] rig')
    rig = build_rig()
    bind(obj, rig)
    print('[figure] occlusion')
    bake_ao(obj)
    print('[figure] motion')
    legs = animate(rig)
    slide = check_feet(obj, rig, legs)
    print('[figure] export')
    export(obj, rig, OUT)
    raw = os.path.getsize(OUT)
    cycle = WALK_FRAMES / FPS
    extras = {'heightM': HEIGHT_M, 'walkCycleS': round(cycle, 6), 'strideM': STRIDE_M,
              'walkSpeedMps': round(STRIDE_M / cycle, 6), 'idleS': IDLE_FRAMES / FPS}
    doc = compact(OUT, extras)
    zs = [v.co.z for v in obj.data.vertices]
    print(f'[figure] {os.path.relpath(OUT)}: {tris} triangles, {len(obj.data.vertices)} vertices, '
          f'{len(doc["skins"][0]["joints"])} joints, clips {[a["name"] for a in doc["animations"]]}, '
          f'height {max(zs) - min(zs):.3f} m, {raw} -> {os.path.getsize(OUT)} bytes, foot slide {slide * 1000:.1f} mm/s, '
          f'{time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
