"""Arduino UNO Q: the receiver, on a tilted plate so the room's camera sees its face.

Positions come from Arduino's top-view drawing of the board (ABX00162), measured in millimetres from the
board's top-left corner with the USB-C end on the left, the way the drawing shows it. The board is
68.58 x 53.34 mm, the UNO footprint, with its stepped edge on the right.
"""

import math

from mathutils import Matrix, Vector

from kit import BODY, DETAIL, MM, Model, circle, fillet_polygon, rounded_rect

W, H = 68.58, 53.34  # board, mm
PCB = 1.6
TILT = math.radians(50)  # the board leans back this far from upright, nearly square to the room's camera


def _p(ix, iy):
    """Drawing millimetres (from the top-left, y down) to board millimetres (from the centre, y up)."""
    return ix - W / 2, H / 2 - iy


def _ccw(corners):
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(corners, corners[1:] + corners[:1]))
    return corners if area > 0 else list(reversed(corners))


def _outline(points, seg90=3):
    return fillet_polygon(_ccw([(_p(x, y)[0] * MM, _p(x, y)[1] * MM, r * MM) for x, y, r in points]), seg90)


def _scaled(points):
    return [(x * MM, y * MM, r) for x, y, r in points]


def _rect(m, ix0, ix1, iy0, iy1, h, mat, top=0.15, z0=0.0, paint=1.0, mat_top=None):
    x0, y1 = _p(ix0, iy0)
    x1, y0 = _p(ix1, iy1)
    m.box(x0 * MM, x1 * MM, y0 * MM, y1 * MM, z0 * MM, (z0 + h) * MM, mat=mat, top=top * MM, paint=paint,
          mat_top=mat_top)


def _dot(m, ix, iy, half, mat, z, paint=1.0, diamond=False):
    x, y = _p(ix, iy)
    if diamond:
        pts = [(x + half, y, 0), (x, y + half, 0), (x - half, y, 0), (x, y - half, 0)]
    else:
        pts = [(x - half, y - half, 0), (x + half, y - half, 0), (x + half, y + half, 0), (x - half, y + half, 0)]
    m.decal(fillet_polygon(_scaled(pts)), z * MM, mat=mat, paint=paint)


def _header(m, cx, cy, pins, rows=1, pitch=2.54, height=8.5, pin_mat=DETAIL, pin_paint=0.32, shroud=0.0):
    """A pin header (female by default: tall, black, square holes) centred on drawing point (cx, cy)."""
    length = pins * pitch + shroud
    width = rows * pitch + shroud
    _rect(m, cx - length / 2, cx + length / 2, cy - width / 2, cy + width / 2, height, DETAIL, top=0.25)
    hole = 0.42 if pin_mat == DETAIL else 0.32
    for r in range(rows):
        for k in range(pins):
            px = cx - (pins - 1) * pitch / 2 + k * pitch
            py = cy - (rows - 1) * pitch / 2 + r * pitch
            _dot(m, px, py, hole, pin_mat, height + 0.06, paint=pin_paint)


def build():
    m = Model("unoq")
    # Board frame: x along the board, y up the board, z out of its face. It leans back by TILT and its
    # front (the components) faces -y in Blender, which is the screen's +z, towards the square's centre.
    up = Vector((0, math.sin(TILT), math.cos(TILT)))
    face = Vector((0, -math.cos(TILT), math.sin(TILT)))
    board = Matrix((
        (1, up.x, face.x, 0),
        (0, up.y, face.y, 0),
        (0, up.z, face.z, 0),
        (0, 0, 0, 1),
    ))
    m.at(board)

    # The board, with the UNO's stepped right edge.
    outline = _outline([
        (0, 0, 0.96), (66.12, 0, 0.96), (66.12, 12.4, 0), (68.58, 14.86, 0.3), (68.58, 48.48, 0.3),
        (66.12, 50.94, 0), (66.12, 53.34, 0.96), (0, 53.34, 0.96),
    ])
    m.slab(outline, -PCB * MM, 0, top=0.25 * MM, segs_top=1, mat=BODY)

    # Mounting holes, drawn as dark discs on the face.
    for ix, iy in ((14.87, 2.59), (13.87, 50.86), (66.06, 17.75), (66.06, 45.81)):
        x, y = _p(ix, iy)
        m.decal(circle(1.6 * MM, 12, x * MM, y * MM), 0.08 * MM, mat=DETAIL, paint=0.55)

    # Headers: digital along the top edge, power and analog along the bottom.
    _header(m, 30.03, 2.53, 10)
    _header(m, 54.56, 2.53, 8)
    _header(m, 37.3, 50.9, 8)
    _header(m, 57.2, 50.9, 6)
    # The debug header (JCTL) and the SPI header: low shrouded blocks with their pins showing.
    _header(m, 18.39, 8.84, 5, rows=2, height=3.2, pin_mat=BODY, pin_paint=0.85, shroud=-0.2)
    _header(m, 64.95, 25.42, 2, rows=3, pitch=2.56, height=2.6, pin_mat=BODY, pin_paint=0.85, shroud=-0.2)

    # USB-C on the left end: a metal shell with a dark mouth facing out.
    cy = _p(0, 15.39)[1]
    shell = rounded_rect(8.94 * MM, 3.26 * MM, 1.55 * MM, seg90=3)
    # The shell's own frame: x across the mouth, y its height, z its axis with the mouth at z = 0.
    usb = Matrix((
        (0, 0, -1, _p(-0.6, 0)[0] * MM),
        (-1, 0, 0, cy * MM),
        (0, 1, 0, 1.63 * MM),
        (0, 0, 0, 1),
    ))
    m.at(board @ usb)
    m.slab(shell, -7.35 * MM, 0, top=0.35 * MM, segs_top=2, mat=BODY, mat_top=DETAIL, cap_bottom=False,
           top_paint=0.45)
    m.decal(rounded_rect(6.9 * MM, 1.5 * MM, 0.7 * MM, seg90=2), 0.05 * MM, mat=DETAIL, paint=0.9)
    m.at(board)

    # Power button: a tactile switch with a round cap.
    _rect(m, 3.09, 9.09, 0.76, 6.76, 3.1, BODY, top=0.3)
    x, y = _p(6.09, 3.76)
    m.slab(circle(1.75 * MM, 12, x * MM, y * MM), 3.1 * MM, 4.4 * MM, top=0.45 * MM, segs_top=2, mat=BODY,
           cap_bottom=False)

    # The chips: Dragonwing SoC, LPDDR4 and the power manager, then the smaller parts.
    _rect(m, 27.03, 41.52, 6.45, 16.42, 1.1, DETAIL, top=0.25)
    _rect(m, 28.1, 40.47, 17.62, 29.52, 1.1, DETAIL, top=0.25)
    _rect(m, 49.17, 55.75, 11.44, 19.68, 0.9, DETAIL, top=0.2)
    _rect(m, 23.64, 29.62, 36.24, 42.16, 0.9, DETAIL, top=0.2)  # STM32U585 microcontroller
    for ix0, ix1, iy0, iy1 in (
        (14.0, 18.0, 15.36, 19.35), (55.6, 57.7, 7.71, 10.77), (46.1, 48.4, 12.57, 14.23),
        (46.1, 48.4, 15.89, 17.55), (46.9, 48.6, 19.88, 22.2), (50.2, 51.9, 20.4, 22.7),
        (24.0, 26.97, 43.8, 46.8), (9.35, 10.81, 25.2, 28.2), (6.82, 9.21, 21.3, 23.2),
    ):
        _rect(m, ix0, ix1, iy0, iy1, 0.8, DETAIL, top=0.12)
    # A few of the small passives round the SoC, so the board doesn't read as bare.
    for ix, iy, rot in ((44.6, 8.4, 0), (44.6, 10.6, 0), (24.4, 13.6, 1), (42.9, 22.4, 1), (42.9, 25.6, 1),
                        (58.8, 15.6, 1)):
        hx, hy = (0.5, 0.25) if rot == 0 else (0.25, 0.5)
        _rect(m, ix - hx, ix + hx, iy - hy, iy + hy, 0.45, DETAIL, top=0.0, paint=0.9)

    # Wi-Fi and Bluetooth module: a dark base under a notched metal can.
    _rect(m, 5.36, 17.46, 31.38, 47.67, 0.7, DETAIL, top=0.1)
    can = _outline([(12.6, 32.0, 0.3), (17.0, 32.0, 0.3), (17.0, 47.1, 0.3), (5.9, 47.1, 0.3), (5.9, 36.2, 0.3),
                    (12.6, 36.2, 0)], seg90=1)
    m.slab(can, 0.7 * MM, 1.9 * MM, top=0.3 * MM, segs_top=1, mat=BODY, cap_bottom=False)

    # The 13 x 8 LED matrix, every LED off, on a slightly darker field so it reads as one patch from afar.
    x0, y1 = _p(31.3, 32.9)
    x1, y0 = _p(58.5, 48.8)
    m.decal(fillet_polygon([(x0 * MM, y0 * MM, 0), (x1 * MM, y0 * MM, 0), (x1 * MM, y1 * MM, 0), (x0 * MM, y1 * MM, 0)]),
            0.06 * MM, mat=BODY, paint=0.84)
    for c in range(13):
        for r in range(8):
            _dot(m, 32.29 + c * 2.106, 33.84 + r * 2.015, 0.62, DETAIL, 0.12, paint=0.9, diamond=True)

    # Qwiic connector at the right edge, its mouth facing out.
    _rect(m, 63.87, 68.2, 36.6, 41.6, 2.9, BODY, top=0.2)
    x0, y1 = _p(68.2, 37.4)
    _, y0 = _p(68.2, 40.8)
    m.box(x0 * MM, (x0 + 0.06) * MM, y0 * MM, y1 * MM, 0.5 * MM, 2.4 * MM, mat=DETAIL, paint=0.6)

    # The holder: four standoffs through the holes to a back plate, a boss, and a ball joint on the pole.
    for ix, iy in ((14.87, 2.59), (13.87, 50.86), (66.06, 17.75), (66.06, 45.81)):
        x, y = _p(ix, iy)
        m.slab(circle(1.7 * MM, 8, x * MM, y * MM), -6.1 * MM, -PCB * MM, mat=DETAIL, cap_top=False,
               cap_bottom=False)
    plate = rounded_rect(56.5 * MM, 51.6 * MM, 4.0 * MM, seg90=2, cx=5.0 * MM, cy=-0.6 * MM)
    m.slab(plate, -8.6 * MM, -6.1 * MM, top=0.8 * MM, bottom=0.8 * MM, segs_top=1, segs_bottom=1, mat=DETAIL)
    # The ball sits on the vertical line through the board's centre, so the pole stands right under it.
    ball_r = 4.6
    ball_z = -10.6 - ball_r + 1.0  # board-frame depth of the ball's centre: just into the boss
    world_z = ball_z / math.sin(TILT)  # its height under the board's centre
    boss_y = world_z * math.cos(TILT)
    m.slab(circle(5.5 * MM, 14, 0, boss_y * MM), -10.6 * MM, -8.6 * MM, bottom=0.6 * MM, segs_bottom=1,
           mat=DETAIL, cap_top=False)
    m.at(Matrix.Translation((0, 0, world_z * MM)))
    m.sphere(ball_r * MM, seg=10, rings=5, mat=DETAIL)
    m.at(Matrix.Identity(4))

    m.empty("anchor", (0, 0, 0))
    m.empty("mount", (0, 0, world_z * MM))
    return m
