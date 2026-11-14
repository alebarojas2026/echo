"""Building blocks for the device models: outlines, rounded slabs with clean normals, baked ambient
occlusion in a colour attribute, and GLB export.

Everything is built as plain vertex and face lists first (a Model), so every normal is set on purpose and
the triangle count is known before Blender sees it. Units are metres at real size; the screen scales the
models up (DISPLAY_SCALE in devices.ts). Blender axes: x right, y back, z up, so a model's front faces -y.
The glTF exporter turns that into three.js axes: y up, front facing +z.
"""

import math

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

MM = 0.001

# Two materials for every model. The screen swaps them for its own two shared materials by name and
# takes the actual greys from web/src/room/palette.ts; the colours here only make Blender previews readable.
BODY = "device"  # light matte grey: bodies, cases, the board itself
DETAIL = "detail"  # darker grey: chips, headers, screens, ports, stands
_PREVIEW = {BODY: (0.6, 0.62, 0.65, 1.0), DETAIL: (0.05, 0.055, 0.06, 1.0)}


# ---------------------------------------------------------------------------------------------- outlines


class Outline:
    """A closed 2D outline, counter-clockwise. Each point carries the outward normal of the edge arriving at
    it and of the edge leaving it: equal on smooth stretches (arcs), different at sharp corners."""

    def __init__(self, pts, n_in, n_out):
        self.pts = [Vector(p) for p in pts]
        self.n_in = [Vector(n).normalized() for n in n_in]
        self.n_out = [Vector(n).normalized() for n in n_out]

    def __len__(self):
        return len(self.pts)

    def offset(self, d):
        """The outline moved inward by d (negative d moves it out). Sharp corners are mitred."""
        pts = []
        for p, a, b in zip(self.pts, self.n_in, self.n_out):
            m = a + b
            m = m / (1.0 + a.dot(b)) if (1.0 + a.dot(b)) > 1e-6 else a
            pts.append(p - m * d)
        return Outline(pts, self.n_in, self.n_out)

    def smooth_normals(self):
        """Normals for vertices shared by both neighbouring faces (used by caps and decals)."""
        return [(a + b).normalized() for a, b in zip(self.n_in, self.n_out)]


def _edge_normal(a, b):
    d = (b - a).normalized()
    return Vector((d.y, -d.x))


def fillet_polygon(corners, seg90=4):
    """Outline through polygon corners [(x, y, r)], counter-clockwise; r > 0 rounds that corner with an arc
    of radius r tangent to both edges, r = 0 keeps it sharp. seg90 is the arc segment count per 90 degrees."""
    P = [Vector((c[0], c[1])) for c in corners]
    n = len(P)
    pts, n_in, n_out = [], [], []
    for i, c in enumerate(corners):
        r = c[2]
        a, p, b = P[i - 1], P[i], P[(i + 1) % n]
        e_in = _edge_normal(a, p)
        e_out = _edge_normal(p, b)
        if r <= 0:
            pts.append(p)
            n_in.append(e_in)
            n_out.append(e_out)
            continue
        d1 = (a - p).normalized()
        d2 = (b - p).normalized()
        half = d1.angle(d2) / 2.0
        t = r / math.tan(half)
        centre = p + (d1 + d2).normalized() * (r / math.sin(half))
        t1 = p + d1 * t
        t2 = p + d2 * t
        turn = math.pi - 2.0 * half
        steps = max(1, round(seg90 * turn / (math.pi / 2)))
        convex = (p - a).cross(b - p) > 0  # counter-clockwise outline: a left turn is convex
        a0 = math.atan2(t1.y - centre.y, t1.x - centre.x)
        a1 = math.atan2(t2.y - centre.y, t2.x - centre.x)
        da = a1 - a0
        while da > math.pi:
            da -= 2 * math.pi
        while da < -math.pi:
            da += 2 * math.pi
        for k in range(steps + 1):
            ang = a0 + da * k / steps
            q = centre + Vector((math.cos(ang), math.sin(ang))) * r
            nrm = (q - centre).normalized() if convex else (centre - q).normalized()
            pts.append(q)
            n_in.append(nrm)
            n_out.append(nrm)
    return Outline(pts, n_in, n_out)


def rounded_rect(w, h, r, seg90=4, cx=0.0, cy=0.0):
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    return fillet_polygon([(x0, y0, r), (x1, y0, r), (x1, y1, r), (x0, y1, r)], seg90)


def circle(r, seg, cx=0.0, cy=0.0, start=0.0):
    pts, nrm = [], []
    for k in range(seg):
        a = start + 2 * math.pi * k / seg
        nrm.append((math.cos(a), math.sin(a)))
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return Outline(pts, nrm, nrm)


# ------------------------------------------------------------------------------------------------- model


class Model:
    """Vertex and face lists with a normal for every face corner, a material and a paint factor per face.
    Paint darkens a face on purpose (a pin hole, an LED) on top of the baked occlusion."""

    def __init__(self, name):
        self.name = name
        self.verts = []
        self.faces = []  # vertex index tuples
        self.normals = []  # per face: one normal per corner
        self.mats = []  # per face: BODY or DETAIL
        self.paint = []  # per face: shade multiplier, 1 = as baked
        self.ao = []  # per face: whether the face takes baked occlusion
        self.matrix = Matrix.Identity(4)
        self.empties = {}

    # Everything added is moved by the current matrix (positions) and its rotation (normals).
    def at(self, matrix):
        self.matrix = matrix
        return self

    def _v(self, p):
        self.verts.append(self.matrix @ Vector(p))
        return len(self.verts) - 1

    def _n(self, n):
        return (self.matrix.to_3x3() @ Vector(n)).normalized()

    def face(self, idx, normals, mat, paint=1.0, ao=True):
        self.faces.append(tuple(idx))
        self.normals.append([self._n(n) for n in normals])
        self.mats.append(mat)
        self.paint.append(paint)
        self.ao.append(ao)

    def empty(self, name, p):
        self.empties[name] = self.matrix @ Vector(p)

    def triangles(self):
        return sum(len(f) - 2 for f in self.faces)

    # --- shapes -------------------------------------------------------------------------------------

    def slab(self, outline, z0, z1, top=0.0, bottom=0.0, segs_top=2, segs_bottom=2, mat=BODY, mat_top=None,
             mat_bottom=None, cap_top=True, cap_bottom=True, top_rings=(), paint=1.0, top_paint=None, ring_paint=None,
             ring_mat=None, skip_sides=()):
        """The outline extruded from z0 to z1. top / bottom round the top and bottom edges over with that
        radius (segs steps; one step is a soft chamfer). top_rings adds inset rings to the top cap so baked
        occlusion has somewhere to go (ring_mat / ring_paint dress them differently from the cap). skip_sides
        leaves out the plain wall for those outline edges."""
        rings = []  # (outline, z, normal weights (side, up)) from bottom to top

        def ring(d, z, s, u):
            rings.append((outline.offset(d) if d else outline, z, s, u))

        if bottom > 0:
            for k in range(segs_bottom + 1):
                phi = (math.pi / 2) * k / segs_bottom  # 0 = bottom cap, 90 = wall
                ring(bottom * (1 - math.sin(phi)), z0 + bottom * (1 - math.cos(phi)), math.sin(phi), -math.cos(phi))
        else:
            ring(0, z0, 1.0, 0.0)
        if top > 0:
            for k in range(segs_top + 1):
                phi = (math.pi / 2) * (1 - k / segs_top)  # 90 = wall, 0 = top cap
                ring(top * (1 - math.sin(phi)), z1 - top * (1 - math.cos(phi)), math.sin(phi), math.cos(phi))
        else:
            ring(0, z1, 1.0, 0.0)

        n = len(outline)
        ids = [[self._v((o.pts[i].x, o.pts[i].y, z)) for i in range(n)] for o, z, _, _ in rings]

        def nrm(r, i, which):
            o, _, s, u = rings[r]
            n2 = (o.n_out if which == "out" else o.n_in)[i]
            return Vector((n2.x * s, n2.y * s, u)).normalized()

        for r in range(len(rings) - 1):
            # a flat wall between the last bottom ring and the first top ring is skippable
            wall = abs(rings[r][3]) < 1e-9 and abs(rings[r + 1][3]) < 1e-9
            for i in range(n):
                j = (i + 1) % n
                if wall and i in skip_sides:
                    continue
                self.face(
                    (ids[r][i], ids[r][j], ids[r + 1][j], ids[r + 1][i]),
                    (nrm(r, i, "out"), nrm(r, j, "in"), nrm(r + 1, j, "in"), nrm(r + 1, i, "out")),
                    mat,
                    paint,
                )
        up = Vector((0, 0, 1))
        if cap_top:
            outer = ids[-1]
            d0 = top
            for d in top_rings:
                inner_o = outline.offset(d0 + d) if (d0 + d) else outline
                inner = [self._v((p.x, p.y, z1)) for p in inner_o.pts]
                for i in range(n):
                    j = (i + 1) % n
                    self.face((outer[i], outer[j], inner[j], inner[i]), (up,) * 4, ring_mat or mat_top or mat,
                              ring_paint if ring_paint is not None else top_paint if top_paint is not None else paint)
                outer = inner
                d0 += d
            self.face(outer, (up,) * n, mat_top or mat, top_paint if top_paint is not None else paint)
        if cap_bottom:
            self.face(list(reversed(ids[0])), (-up,) * n, mat_bottom or mat, paint)
        return ids

    def box(self, x0, x1, y0, y1, z0, z1, mat=BODY, top=0.0, segs=1, paint=1.0, mat_top=None, cap_bottom=False):
        o = fillet_polygon([(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)])
        return self.slab(o, z0, z1, top=top, segs_top=segs, mat=mat, mat_top=mat_top, paint=paint,
                         cap_bottom=cap_bottom)

    def decal(self, outline, z, mat=DETAIL, paint=1.0, ao=False):
        """A flat face lying on a surface (an LED, a pin hole, a screen), facing +z."""
        idx = [self._v((p.x, p.y, z)) for p in outline.pts]
        self.face(idx, ((0, 0, 1),) * len(idx), mat, paint, ao)

    def tube(self, outline, z0, z1, mat=BODY, paint=1.0, inward=False):
        """Open walls only (a pole, the inside of an opening). inward flips them to face the axis."""
        n = len(outline)
        lo = [self._v((p.x, p.y, z0)) for p in outline.pts]
        hi = [self._v((p.x, p.y, z1)) for p in outline.pts]
        for i in range(n):
            j = (i + 1) % n
            a = Vector((outline.n_out[i].x, outline.n_out[i].y, 0))
            b = Vector((outline.n_in[j].x, outline.n_in[j].y, 0))
            if inward:
                self.face((lo[j], lo[i], hi[i], hi[j]), (-b, -a, -a, -b), mat, paint)
            else:
                self.face((lo[i], lo[j], hi[j], hi[i]), (a, b, b, a), mat, paint)

    def sphere(self, r, seg=12, rings=6, mat=DETAIL, paint=1.0):
        """A UV sphere around the current origin, with single vertices at the poles."""
        top = self._v((0, 0, r))
        bottom = self._v((0, 0, -r))
        rows = []
        for k in range(1, rings):
            th = math.pi * k / rings
            rows.append([self._v((r * math.sin(th) * math.cos(2 * math.pi * s / seg),
                                  r * math.sin(th) * math.sin(2 * math.pi * s / seg), r * math.cos(th)))
                         for s in range(seg)])
        inv = self.matrix.to_3x3().inverted()
        centre = self.matrix @ Vector((0, 0, 0))

        def nrm(i):
            return inv @ (self.verts[i] - centre)

        for s in range(seg):
            t = (s + 1) % seg
            a, b = rows[0][s], rows[0][t]
            self.face((top, a, b), (nrm(top), nrm(a), nrm(b)), mat, paint)
            a, b = rows[-1][s], rows[-1][t]
            self.face((bottom, b, a), (nrm(bottom), nrm(b), nrm(a)), mat, paint)
            for k in range(len(rows) - 1):
                q = (rows[k][s], rows[k + 1][s], rows[k + 1][t], rows[k][t])
                self.face(q, [nrm(i) for i in q], mat, paint)


# ------------------------------------------------------------------------------------------------- bake


def _hemisphere(n):
    """n cosine-weighted directions around +z (a Hammersley set, so every bake is identical)."""
    out = []
    for i in range(n):
        u = (i + 0.5) / n
        bits = i
        v = 0.0
        f = 0.5
        while bits:
            v += f * (bits & 1)
            bits >>= 1
            f *= 0.5
        r = math.sqrt(u)
        a = 2 * math.pi * v
        out.append(Vector((r * math.cos(a), r * math.sin(a), math.sqrt(max(0.0, 1 - u)))))
    return out


def bake_occlusion(model, reach, samples=160, strength=0.85):
    """Ambient occlusion per face corner, softened by strength and multiplied by each face's paint.
    reach is how far (metres) a surface looks for something blocking its sky.

    Only quads (walls, bevel strips, cap rings) take occlusion. A large n-gon cap has corners only round its
    edge, so occlusion at one corner would smear across the whole face in long streaks; caps keep one tone."""
    tree = BVHTree.FromPolygons(model.verts, model.faces, all_triangles=False, epsilon=0.0)
    dirs = _hemisphere(samples)
    cache = {}
    shade = []
    eps = 0.03 * MM
    for f, (face, nrms) in enumerate(zip(model.faces, model.normals)):
        corner = []
        for vi, n in zip(face, nrms):
            if not model.ao[f] or len(face) > 4:
                corner.append(model.paint[f])
                continue
            key = (vi, round(n.x, 3), round(n.y, 3), round(n.z, 3))
            if key not in cache:
                t = n.orthogonal().normalized()
                b = n.cross(t)
                origin = model.verts[vi] + n * eps
                occ = 0.0
                for d in dirs:
                    w = t * d.x + b * d.y + n * d.z
                    hit, _, _, dist = tree.ray_cast(origin, w, reach)
                    if hit is not None:
                        occ += 1.0 - (dist / reach) ** 2
                cache[key] = 1.0 - occ / len(dirs)
            ao = cache[key]
            corner.append((1.0 - strength * (1.0 - ao)) * model.paint[f])
        shade.append(corner)
    return shade


# ------------------------------------------------------------------------------------------------ export


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _material(name):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        m.diffuse_color = _PREVIEW[name]
        m.roughness = 0.8
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = _PREVIEW[name]
            bsdf.inputs["Roughness"].default_value = 0.8
    return m


def to_object(model, shade):
    """A Blender mesh object with the model's corner normals, two material slots and the baked shade."""
    me = bpy.data.meshes.new(model.name)
    me.from_pydata([tuple(v) for v in model.verts], [], [list(f) for f in model.faces])
    slots = [BODY, DETAIL]
    for s in slots:
        me.materials.append(_material(s))
    for poly, mat in zip(me.polygons, model.mats):
        poly.material_index = slots.index(mat)
        poly.use_smooth = True
    loop_normals = [None] * len(me.loops)
    col = me.color_attributes.new("shade", "FLOAT_COLOR", "CORNER")
    for poly, nrms, sh in zip(me.polygons, model.normals, shade):
        for k, li in enumerate(poly.loop_indices):
            loop_normals[li] = tuple(nrms[k])
            v = sh[k]
            col.data[li].color = (v, v, v, 1.0)
    me.normals_split_custom_set(loop_normals)
    me.color_attributes.active_color = col
    me.color_attributes.render_color_index = me.color_attributes.find("shade")
    me.validate(clean_customdata=False)
    obj = bpy.data.objects.new(model.name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def export_glb(path, objects, empties):
    """Writes the objects and the named points (empties) as one GLB, with no textures or UVs."""
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for name, p in empties.items():
        e = bpy.data.objects.new(name, None)
        e.location = p
        bpy.context.scene.collection.objects.link(e)
        e.select_set(True)
    for o in objects:
        o.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_normals=True,
        export_texcoords=False,
        export_tangents=False,
        export_materials="EXPORT",
        export_vertex_color="ACTIVE",
        export_all_vertex_colors=False,
        export_attributes=False,
        export_extras=False,
        export_cameras=False,
        export_lights=False,
        export_animations=False,
        export_skins=False,
        export_morph=False,
    )


def triangle_count(obj):
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)


def bounds(model):
    xs = [v.x for v in model.verts]
    ys = [v.y for v in model.verts]
    zs = [v.z for v in model.verts]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
