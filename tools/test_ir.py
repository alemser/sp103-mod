#!/usr/bin/env python3
"""Checks the bits in firmware/ir_codes.py against the SP103 profile in groove-rig.

    python3 tools/test_ir.py
"""

import base64
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))

import ir_codes   # noqa: E402

PROFILE = os.path.expanduser("~/Projects/groove-rig/internal/catalog/profiles/acoustic_solutions_sp103.yaml")
TICK_US = 269 / 8.192           # Broadlink time unit
LONG_US = 1000                  # above this, the space is a 1 bit


def captured(body):
    """The timings in µs of a Broadlink code, up to the end of the first repeat signal."""
    data = base64.b64decode(body)
    payload = data[4:4 + (data[2] | data[3] << 8)]
    times, i = [], 0
    while i < len(payload):
        value = payload[i]
        i += 1
        if value == 0:
            value = payload[i] << 8 | payload[i + 1]
            i += 2
        times.append(value * TICK_US)
    return times[:91]


with open(PROFILE) as f:
    codes = dict(re.findall(r"^  (\w+):\n\s+format: broadlink_ir\n\s+body: (\S+)", f.read(), re.M))

assert set(codes) == set(ir_codes.COMMANDS)
for name, body in codes.items():
    words = ir_codes.frame(name)
    # Pairs of line low and released: the PIO always ends waiting for the next line-low.
    assert len(words) % 2 == 0
    want = captured(body)
    assert len(want) == len(words) - 1, name
    # Bits only: the Broadlink timings are about 5% longer than the real remote's.
    for i, (a, b) in enumerate(zip(words, want)):
        assert (a > LONG_US) == (b > LONG_US), (name, i, a, round(b))

print("all good")
