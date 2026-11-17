#!/usr/bin/env python3
"""Tests who stays on /events (firmware/listeners.py) on the computer.

    python3 tools/test_listeners.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))

from listeners import MAX_LISTENERS, make_room   # noqa: E402

rig, phone, mac, other = "10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"

a = [(rig, "w1"), (phone, "w2")]
make_room(a, phone)
assert a == [(rig, "w1")], "the same IP replaces its old connection and keeps the rig"

a = [(phone, "w1"), (phone, "w2"), (rig, "w3")]
make_room(a, phone)
assert a == [(rig, "w3")], "all of the IP's old connections go"

a = [(rig, "w1"), (phone, "w2"), (mac, "w3")]
make_room(a, other)
assert a == [(phone, "w2"), (mac, "w3")] and len(a) < MAX_LISTENERS, "full: the oldest one goes"

a = [(rig, "w1")]
make_room(a, phone)
assert a == [(rig, "w1")], "with room to spare, nobody goes"

a = [(None, "w1"), (None, "w2")]
make_room(a, None)
assert len(a) == 2, "an unknown IP doesn't count as the same client"
print("all good")
