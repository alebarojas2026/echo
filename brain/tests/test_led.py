"""The LED grid over the Bridge: a dead Bridge must not slow the live loop."""
from brain.alert import LED_RETRY_S, BridgeLed


def test_a_failing_bridge_is_left_alone_for_a_while_then_tried_again():
    calls, now, up = [], [100.0], [False]

    def call(name, *args, timeout):
        calls.append((name, *args))
        if not up[0]:
            raise TimeoutError("no answer from the microcontroller")

    led = BridgeLed(call=call, clock=lambda: now[0])
    led.show_zone(1)                       # fails (on the board: after its 1 s timeout)
    for zone in (2, 3, 4):                 # the next zone changes don't each wait another second
        now[0] += 1
        led.show_zone(zone)
    led.alert(True)
    assert calls == [("show_zone", 1)]
    now[0] += LED_RETRY_S
    up[0] = True                           # the Bridge is back
    led.show_zone(2)
    led.smile()
    assert calls == [("show_zone", 1), ("show_zone", 2), ("smile",)]
