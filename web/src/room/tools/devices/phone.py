"""A modern phone, used as a Bluetooth beacon, standing in a small desk stand.

147 x 71.5 x 7.85 mm with 10.5 mm corners: today's common 6.1 inch size. It leans back 22 degrees in a
stand with a front lip, a back rest and a base plate. No brand marks: a dark screen with a thin bezel and
a camera island on the back.
"""

import math

from mathutils import Matrix, Vector

from kit import BODY, DETAIL, MM, Model, circle, fillet_polygon, rounded_rect

PW, PH, PT = 71.5, 147.0, 7.85  # width, height, thickness, mm
CORNER = 10.5
EDGE = 1.6  # front and back edge roundover
LEAN = math.radians(22)
GAP = 0.2  # between the phone and its stand, so the two never fight for the same pixels
PLATE_TOP = -74.0  # mm, below the phone's centre


def _frame():
    """Phone frame: x across, y up the phone, z out of the screen. It leans back by LEAN, screen to -y."""
    up = Vector((0, math.sin(LEAN), math.cos(LEAN)))
    face = Vector((0, -math.cos(LEAN), math.sin(LEAN)))
    return Matrix(((1, up.x, face.x, 0), (0, up.y, face.y, 0), (0, up.z, face.z, 0), (0, 0, 0, 1)))


def _phone(m, frame):
    m.at(frame)
    th = PT / 2
    body = rounded_rect(PW * MM, PH * MM, CORNER * MM, seg90=5)
    # The frame is light; the glass front is darker than the stand, with a darker bezel round the screen.
    m.slab(body, -th * MM, th * MM, top=EDGE * MM, bottom=EDGE * MM, segs_top=2, segs_bottom=2, mat=BODY,
           mat_top=DETAIL, top_rings=(1.4 * MM,), ring_paint=0.5, top_paint=0.72, mat_bottom=BODY)
    top_of_screen = PH / 2 - EDGE - 1.4
    m.decal(rounded_rect(19 * MM, 5.4 * MM, 2.7 * MM, seg90=2, cy=(top_of_screen - 5.5) * MM), (th + 0.06) * MM,
            mat=DETAIL, paint=0.38)

    # Camera island on the back, top right as you face the screen, with two lenses.
    cx, cy = PW / 2 - 4.6 - 18.0, PH / 2 - 4.6 - 18.0
    island = rounded_rect(36 * MM, 36 * MM, 9 * MM, seg90=4, cx=cx * MM, cy=cy * MM)
    m.slab(island, -(th + 1.5) * MM, -(th - 0.3) * MM, bottom=0.7 * MM, segs_bottom=2, mat=BODY, paint=0.9,
           cap_top=False)
    back = frame @ Matrix.Rotation(math.pi, 4, "Y")  # decals facing out of the back
    m.at(back)
    z = (th + 1.5 + 0.06) * MM
    for lx, ly in ((cx + 8.2, cy + 8.2), (cx - 8.2, cy - 8.2)):
        m.decal(circle(7.0 * MM, 20, -lx * MM, ly * MM), z, mat=DETAIL, paint=0.85)
        m.decal(circle(4.2 * MM, 16, -lx * MM, ly * MM), z + 0.05 * MM, mat=DETAIL, paint=0.42)

    # Side buttons: power on the right, action and volume on the left.
    right = frame @ Matrix(((0, 0, 1, (PW / 2 - 0.2) * MM), (0, 1, 0, 0), (-1, 0, 0, 0), (0, 0, 0, 1)))
    left = frame @ Matrix(((0, 0, -1, -(PW / 2 - 0.2) * MM), (0, 1, 0, 0), (1, 0, 0, 0), (0, 0, 0, 1)))
    for side, y, length in ((right, 20.0, 16.0), (left, 45.0, 6.0), (left, 30.0, 9.5), (left, 18.0, 9.5)):
        m.at(side)
        m.slab(rounded_rect(2.8 * MM, length * MM, 1.2 * MM, seg90=1, cy=y * MM), 0, 1.1 * MM, top=0.45 * MM,
               segs_top=1, mat=BODY, paint=0.95, cap_bottom=False)
    m.at(Matrix.Identity(4))


def _stand(m):
    """A side profile (lip, cradle, back rest) extruded across, on a rounded base plate."""
    th = PT / 2 + GAP
    s, c = math.sin(LEAN), math.cos(LEAN)

    def world(sy, sz):  # a point of the phone's side section to (y, z) in mm
        return sy * s - sz * c, sy * c + sz * s

    def on_plate(sz, z):  # the point at depth sz in the phone frame whose height is z
        return world((z - sz * s) / c, sz)

    bottom = PLATE_TOP - 1.0
    rest = th + 6.0  # back rest thickness behind the phone
    lip = 4.0
    pts = [
        (*on_plate(-rest, bottom), 0),
        (*world(-14, -rest), 2.5),
        (*world(-14, -th), 2.5),
        (*world(-(PH / 2 + GAP), -th), 0),
        (*world(-(PH / 2 + GAP), th), 0),
        (*world(-PH / 2 + 7, th), 1.5),
        (*world(-PH / 2 + 7, th + lip), 1.5),
        (*on_plate(th + lip, bottom), 0),
    ]
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
    if area < 0:
        pts.reverse()
    profile = fillet_polygon([(y * MM, z * MM, r * MM) for y, z, r in pts], seg90=2)
    # Profile frame: x is the stand's depth (y), y its height (z), z across (x).
    m.at(Matrix(((0, 0, 1, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1))))
    m.slab(profile, -28 * MM, 28 * MM, top=1.2 * MM, bottom=1.2 * MM, segs_top=2, segs_bottom=2, mat=DETAIL)
    m.at(Matrix.Identity(4))
    front = on_plate(th + lip, PLATE_TOP)[0] - 5.0
    plate = rounded_rect(70 * MM, (24 - front) * MM, 12 * MM, seg90=3, cy=(24 + front) / 2 * MM)
    m.slab(plate, (PLATE_TOP - 6) * MM, PLATE_TOP * MM, top=2.0 * MM, bottom=0.6 * MM, segs_top=2, segs_bottom=1,
           mat=DETAIL, top_rings=(5.0 * MM,))
    m.slab(circle(6.5 * MM, 16), (PLATE_TOP - 16) * MM, (PLATE_TOP - 6) * MM, bottom=1.2 * MM, segs_bottom=2,
           mat=DETAIL, cap_top=False)
    return (PLATE_TOP - 13) * MM


def build():
    m = Model("phone")
    _phone(m, _frame())
    mount = _stand(m)
    m.empty("anchor", (0, 0, 0))
    m.empty("mount", (0, 0, mount))
    return m
