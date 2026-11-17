#!/usr/bin/env python3
"""Tests the direct controls (firmware/control.py) on the computer, with a fake amp.

    python3 tools/test_control.py
"""

import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))

asyncio.sleep_ms = lambda ms: asyncio.sleep(0)   # no real waiting in the tests

import control   # noqa: E402

ORDER = ("normal", "bass", "treble", "balance", "loudness", "speakers")


class FakeAmp:
    """Stands in for the state, the IR and the panel. glitch: clicks on which the amp also jumps to PHONO."""

    def __init__(self, glitch=()):
        self.power, self.screen, self.input_id = "on", "normal", "cd"
        self.volume_db, self.bass_db, self.treble_db, self.balance = -40.0, 2, 0, 0
        self.loudness, self.speakers = False, True
        self.opened = False
        self.glitch = set(glitch)
        self.presses = 0
        self.keys = []

    def sending(self):
        return False

    def press(self):
        self.presses += 1
        self.screen = ORDER[(ORDER.index(self.screen) + 1) % len(ORDER)]
        if self.presses in self.glitch:
            self.input_id = "phono"

    def send(self, key):
        self.keys.append(key)
        sign = 1 if key == "volume_up" else -1
        if key.startswith("select_"):
            self.input_id = key[7:]
        elif key in ("bass", "treble"):
            self.screen = key
        elif self.screen in ("bass", "treble"):
            setattr(self, self.screen + "_db", getattr(self, self.screen + "_db") + 2 * sign)
        elif self.screen == "balance":
            self.balance += sign
        elif self.screen in ("loudness", "speakers"):
            setattr(self, self.screen, sign > 0)
        elif self.opened:
            self.volume_db += 1.25 * sign
        else:
            self.opened = True          # the first press only opens the volume screen


def run(amp, **query):
    asyncio.run(control.Control(amp, amp, amp).run(query))


amp = FakeAmp()
run(amp, target="volume", dir="up")
assert amp.volume_db == -38.75 and amp.keys == ["volume_up", "volume_up"]
run(amp, target="volume", dir="down")
assert amp.volume_db == -40 and len(amp.keys) == 3

amp = FakeAmp()
run(amp, target="bass", dir="up")
assert amp.bass_db == 4 and amp.keys == ["bass", "volume_up"] and amp.volume_db == -40
run(amp, target="bass", dir="down")
assert amp.bass_db == 2 and amp.keys == ["bass", "volume_up", "volume_down"]

amp = FakeAmp()
run(amp, target="balance", dir="down")
assert amp.balance == -1 and amp.presses == 3 and amp.screen == "balance"

amp = FakeAmp()
run(amp, target="loudness", on="1")
assert amp.loudness is True and amp.keys == ["volume_up"]
run(amp, target="loudness", on="1")
assert amp.keys == ["volume_up"]    # already on: nothing to change
run(amp, target="speakers", on="0")
assert amp.speakers is False and amp.keys[-1] == "volume_down"

# The click that jumps to PHONO: goes back to the previous input and carries on to the menu.
amp = FakeAmp(glitch=[2])
run(amp, target="loudness", on="1")
assert amp.input_id == "cd" and amp.loudness is True and "select_cd" in amp.keys

for query in ({"target": "x", "dir": "up"}, {"target": "bass"}, {"target": "bass", "dir": "x"},
              {"target": "loudness", "on": "2"}):
    try:
        run(FakeAmp(), **query)
        raise AssertionError(query)
    except ValueError as e:
        assert str(e) == "Unknown control"

# A key also works in standby, and only known ones go through.
amp = FakeAmp()
amp.power = "standby"
run(amp, target="key", name="power_toggle")
assert amp.keys == ["power_toggle"]
try:
    run(amp, target="key", name="x")
    raise AssertionError("unknown key")
except ValueError as e:
    assert str(e) == "Unknown key"

amp = FakeAmp()
amp.power = "standby"
try:
    run(amp, target="volume", dir="up")
    raise AssertionError("standby")
except ValueError as e:
    assert str(e) == "The amp isn't on"
assert amp.keys == []
print("all good")
