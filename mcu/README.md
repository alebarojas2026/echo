# mcu

The sketch for the UNO Q's microcontroller (STM32, `arduino:zephyr:unoq`). It drives the 8 x 13 LED matrix and exposes three Bridge functions to Linux:

| Call | Shows |
|---|---|
| `show_zone(n)` | `0`: a small dot (empty). `1`-`4`: a big digit. `-1`, or anything else: `?` (pred null, blind, or 2+ zones) |
| `alert(on)` | `True`: the zone alternates with a bordered `!` every 0.3 s. `False`: back to the zone |
| `smile()` | a smile for 1.5 s, then back to the alert or the last zone |

Each call only stores the request and returns, and `loop()` does the drawing, so calls come back right away. It shows `?` from power-on until the first `show_zone`.

## Flash (on the board)
```sh
arduino-cli compile --fqbn arduino:zephyr:unoq --upload mcu/
```
If the compile can't find `Arduino_RouterBridge.h`, run `arduino-cli lib install Arduino_RouterBridge` once, before the board joins the hotspot.

## Call it from Linux
Install the `arduino` package from the github.com/arduino/app-bricks-py releases (the `arduino_app_bricks-*.whl`) into the board's `.venv` with `pip install <wheel>`, while the board still has internet. Then any host Python process can do this:
```python
from arduino.app_utils import Bridge

Bridge.call("show_zone", 2, timeout=1)     # big 2
Bridge.call("show_zone", -1, timeout=1)    # ?
Bridge.call("alert", True, timeout=1)      # pass a real bool, not 1
Bridge.call("smile", timeout=1)
```
The Bridge goes through the `arduino-router` service. If calls fail with "Cannot reach the Arduino Router", check `systemctl status arduino-router`.

From brain state (CONTRACTS.md section 5):
- `pred` null, `health.status` blind, or `zone_set` with 2 or more zones: `show_zone(-1)`.
- `pred.present` false: `show_zone(0)`.
- Otherwise: `show_zone(pred.zone)`.
- `alert(alert.state == "check_on")`.
- `smile()` on a `checkin` event.

App Lab apps can carry their own sketch. Make sure the camera teacher app (teacher/applab/) has none, or starting it may replace this one.
