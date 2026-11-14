"""Raspberry Pi 5 in a simple case: the router.

The case is the official Pi 5 case's size, 98.5 x 70.3 x 33 mm, lying flat on a small platform. Its
USB and Ethernet end faces away from the square's centre (towards the room's camera), the power and
HDMI ports are on one long side, and the lid has a round vent over the fan.
"""

import math

from mathutils import Matrix

from kit import BODY, DETAIL, MM, Model, circle, rounded_rect

L, W, H = 98.5, 70.3, 33.0  # depth (y), width (x), height (z), mm
R = 9.0  # corner radius in plan
BASE_TOP = 11.6  # where the base ends and the lid's air gap begins (case centre is z = 0)
LID_BOTTOM = 12.4
BOTTOM_ROUND = 2.2
TOP_ROUND = 0.6


def _ports(m):
    """The USB and Ethernet end: a wall with three openings, each a dark recess (USB ones split in two)."""
    y = L / 2 * MM
    depth = 4.0 * MM
    x_edge = W / 2 - R
    z_lo = -H / 2 + BOTTOM_ROUND
    z_hi = BASE_TOP - TOP_ROUND
    holes = [(-24.4, -8.6), (-6.4, 7.6), (10.0, 24.0)]  # Ethernet, then the two USB pairs (x, mm)
    hz = (-11.6, 5.4)
    # The wall reaches 0.1 mm past its seams, onto the corners and edges that curve away from it, so no
    # pixel-wide crack opens where its extra vertices meet the case's plain bevel strips.
    lap = 0.1
    xs = [-x_edge - lap] + [v for h in holes for v in h] + [x_edge + lap]
    zs = [z_lo - lap, hz[0], hz[1], z_hi + lap]
    grid = [[m._v((x * MM, y, z * MM)) for z in zs] for x in xs]
    out = (0, 1, 0)
    for i in range(len(xs) - 1):
        for k in range(len(zs) - 1):
            if k == 1 and i % 2 == 1:
                continue  # an opening
            m.face((grid[i][k], grid[i][k + 1], grid[i + 1][k + 1], grid[i + 1][k]), (out,) * 4, BODY)
    # Behind the wall: one dark backing for all three openings, so the recesses have a floor.
    back = [m._v((x * MM, y - depth, z * MM)) for x, z in ((-x_edge, z_lo), (-x_edge, z_hi), (x_edge, z_hi), (x_edge, z_lo))]
    m.face(back, (out,) * 4, DETAIL, paint=0.42)
    for x0, x1 in holes:
        a = [(x0, hz[0]), (x1, hz[0]), (x1, hz[1]), (x0, hz[1])]
        inward = [(0, 0, 1), (-1, 0, 0), (0, 0, -1), (1, 0, 0)]  # each recess wall faces into the opening
        for s in range(4):
            (ax, az), (bx, bz) = a[s], a[(s + 1) % 4]
            quad = [m._v((ax * MM, y, az * MM)), m._v((ax * MM, y - depth, az * MM)),
                    m._v((bx * MM, y - depth, bz * MM)), m._v((bx * MM, y, bz * MM))]
            m.face(quad, (inward[s],) * 4, DETAIL, paint=0.75)
    # The USB openings hold two ports each, one above the other.
    for x0, x1 in holes[1:]:
        m.box(x0 * MM, x1 * MM, y - depth, y - 0.5 * MM, -3.9 * MM, -2.3 * MM, mat=BODY, paint=0.8, cap_bottom=True)


def build():
    m = Model("pi5")
    plan = rounded_rect(W * MM, L * MM, R * MM, seg90=4)
    # Base: the +y straight wall (outline edge 14) is left out and rebuilt with the port openings.
    m.slab(plan, -H / 2 * MM, BASE_TOP * MM, top=TOP_ROUND * MM, bottom=BOTTOM_ROUND * MM, segs_top=1,
           segs_bottom=2, mat=BODY, skip_sides=(14,))
    _ports(m)
    # The air gap under the lid, dark all round.
    m.tube(rounded_rect((W - 2.4) * MM, (L - 2.4) * MM, (R - 1.2) * MM, seg90=4), (BASE_TOP - 0.6) * MM,
           (LID_BOTTOM + 0.5) * MM, mat=DETAIL, paint=0.6)
    # The lid.
    m.slab(plan, LID_BOTTOM * MM, H / 2 * MM, top=2.6 * MM, bottom=0.6 * MM, segs_top=3, segs_bottom=1, mat=BODY,
           cap_bottom=False)
    # A round field of vent holes over the fan.
    vx, vy, z = -7.0, -12.0, (H / 2 + 0.06) * MM
    pitch = 3.4
    for row in range(-4, 5):
        for col in range(-4, 5):
            hx = vx + (col + 0.5 * (row % 2)) * pitch
            hy = vy + row * pitch * math.sqrt(3) / 2
            if math.hypot(hx - vx, hy - vy) <= 12.6:
                m.decal(circle(1.15 * MM, 6, hx * MM, hy * MM, start=math.pi / 6), z, mat=DETAIL, paint=0.8)

    # Power (USB-C) and the two micro HDMI ports on the +x side.
    side = Matrix(((0, 0, 1, (W / 2 + 0.08) * MM), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    m.at(side)
    for y, w, h, r in ((-24.8, 9.0, 3.4, 1.5), (-10.2, 6.8, 3.2, 1.0), (3.2, 6.8, 3.2, 1.0)):
        m.decal(rounded_rect(w * MM, h * MM, r * MM, seg90=2, cx=y * MM, cy=-8.0 * MM), 0, mat=DETAIL, paint=0.7)
    m.at(Matrix.Identity(4))

    # A low platform and the socket the pole goes into.
    m.slab(circle(24 * MM, 24), -20.5 * MM, -H / 2 * MM, bottom=1.2 * MM, segs_bottom=1, mat=DETAIL, cap_top=False)
    m.slab(circle(6 * MM, 16), -30 * MM, -20.5 * MM, bottom=1.2 * MM, segs_bottom=2, mat=DETAIL, cap_top=False)

    m.empty("anchor", (0, 0, 0))
    m.empty("mount", (0, 0, -26 * MM))
    return m
