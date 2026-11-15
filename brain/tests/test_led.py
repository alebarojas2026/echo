"""The LED grid over the Bridge: a dead Bridge must not slow the live loop."""
from brain.alert import LED_RETRY_S, BridgeLed


def test_a_failing_bridge_is_left_alone_for_a_while_then_tried_again():
    calls, now, up = [], [100.0], [False]

    def call(name, *args, timeout):
        calls.append((name, *args))
        if not up[0]:
            raise TimeoutError("no answer from the microcontroller")

    led = BridgeLed(call=call, clock=lambda: now[0], run=lambda fn: fn())   # in line, for the test
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


def test_a_slow_bridge_never_holds_the_caller_up_and_calls_made_meanwhile_are_dropped():
    """#648: the Bridge call can take its whole 1 s timeout; it must not run on the live loop."""
    import threading
    import time
    release, started, calls = threading.Event(), threading.Event(), []

    def slow(name, *args, timeout):
        calls.append((name, *args))
        started.set()
        release.wait(5)                    # a Bridge that takes its time

    led = BridgeLed(call=slow)
    t0 = time.monotonic()
    led.show_zone(1)
    assert started.wait(2)
    led.show_zone(2)                       # the first hasn't come back: dropped, not queued
    led.alert(True)
    assert time.monotonic() - t0 < 0.5     # the caller never waited for the Bridge
    assert calls == [("show_zone", 1)] and led.dropped == 2
    release.set()
    deadline = time.monotonic() + 2
    while led._busy and time.monotonic() < deadline:
        time.sleep(0.01)
    led.smile()                            # once it is back, calls go through again
    deadline = time.monotonic() + 2
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls == [("show_zone", 1), ("smile",)]


def test_state_returns_at_once_with_an_led_that_sleeps_a_second():
    import time
    from brain.core import Brain

    def sleepy(name, *args, timeout):
        time.sleep(1.0)

    brain = Brain(led=BridgeLed(call=sleepy))
    t0 = time.monotonic()
    brain.watch.led.show_zone(2)
    brain.state()
    brain.watch.on_pred(1_000, None)       # the alert rules call the grid from the loop
    brain.state()
    assert time.monotonic() - t0 < 0.5
