"""The stand every device sits on: a slim pole on a round foot.

Two meshes so the screen can stretch the pole to each device's height without stretching the foot: the
pole is 1 m long here (unit length) and the screen scales it to reach the device's mount point.
"""

from kit import DETAIL, MM, Model, circle

FOOT_R = 14.5  # mm
FOOT_H = 4.0
POLE_R = 3.5


def build():
    foot = Model("foot")
    # Inset rings on the top let the occlusion gather softly around the pole.
    foot.slab(circle(FOOT_R * MM, 32), 0, FOOT_H * MM, top=1.8 * MM, bottom=0.4 * MM, segs_top=2, segs_bottom=1,
              mat=DETAIL, top_rings=(4.6 * MM, 4.2 * MM), cap_bottom=False)
    pole = Model("pole")
    pole.tube(circle(POLE_R * MM, 20), 0, 1.0, mat=DETAIL)
    return foot, pole
