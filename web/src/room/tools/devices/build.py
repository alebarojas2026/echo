"""Builds the room's device models and writes them to web/src/room/assets/.

    <blender python> web/src/room/tools/devices/build.py

Needs Python with the bpy module (Blender 5.x as a module). Everything runs on the CPU: the occlusion is
ray cast here in Python, so no render engine or GPU is involved. Prints each model's triangle count and
size; the screen's devices.ts tests read the same files.

  unoq.glb   Arduino UNO Q on its tilted plate     (anchor: the board's centre)
  pi5.glb    Raspberry Pi 5 in its case             (anchor: the case's centre)
  phone.glb  phone in a desk stand, used twice      (anchor: the phone's centre)
  stand.glb  foot and a 1 m pole, shared by all four

Every device model has two points: "anchor", the radio's centre, where the screen puts the node's
position, and "mount", where the pole meets the device.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import kit  # noqa: E402
import phone  # noqa: E402
import pi5  # noqa: E402
import stand  # noqa: E402
import unoq  # noqa: E402

ASSETS = HERE.parents[1] / "assets"
BUDGET = 1500  # triangles per model

# How far each model's surfaces look for something blocking their sky, in metres (real size).
REACH = {"unoq": 0.006, "pi5": 0.008, "phone": 0.008, "foot": 0.012}


def main():
    ASSETS.mkdir(exist_ok=True)
    report = []
    for name, builder in (("unoq", unoq.build), ("pi5", pi5.build), ("phone", phone.build)):
        kit.reset_scene()
        model = builder()
        # The pole stands straight under the radio: the screen puts both on the node's floor point.
        anchor, mount = model.empties["anchor"], model.empties["mount"]
        assert anchor.length < 1e-9 and abs(mount.x) < 1e-9 and abs(mount.y) < 1e-9, f"{name}: mount off the axis"
        shade = kit.bake_occlusion(model, REACH[name])
        obj = kit.to_object(model, shade)
        tris = kit.triangle_count(obj)
        kit.export_glb(ASSETS / f"{name}.glb", [obj], model.empties)
        report.append((name, tris, kit.bounds(model)))

    kit.reset_scene()
    foot, pole = stand.build()
    objs = [kit.to_object(foot, kit.bake_occlusion(foot, REACH["foot"]))]
    # The pole is stretched to each device's height on screen, so it carries no occlusion of its own.
    objs.append(kit.to_object(pole, [[1.0] * len(f) for f in pole.faces]))
    tris = sum(kit.triangle_count(o) for o in objs)
    kit.export_glb(ASSETS / "stand.glb", objs, {})
    report.append(("stand", tris, kit.bounds(foot)))

    over = False
    for name, tris, (lo, hi) in report:
        size = " x ".join(f"{(b - a) * 1000:.1f}" for a, b in zip(lo, hi))
        flag = "" if tris <= BUDGET else f"  OVER the {BUDGET} budget"
        over = over or tris > BUDGET
        print(f"{name:6s} {tris:5d} triangles   {size} mm (x, y, z)   z {lo[2] * 1000:.1f} to {hi[2] * 1000:.1f}{flag}")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
