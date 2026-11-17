#!/usr/bin/env python3
"""Tests the screen reader (firmware/amp_state.py).

Without arguments: checks hand-written screens (the ones from the captures, see docs/descobertas-protocolo.md).
With captures: replays each .lac, hands each complete screen to the reader and shows the state when it changes.

    python3 tools/test_amp_state.py
    python3 tools/test_amp_state.py captures/04-phono-b.lac captures/15-balance.lac
    python3 tools/test_amp_state.py --no-rw captures/13-function-todos.lac
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))

import hd44780_decode as hd   # noqa: E402
from amp_state import AmpState, BOX, parse   # noqa: E402

# A screen is complete when the controller goes this long without writing.
QUIET_US = 2000

B = BOX
CASES = [
    # (line 1, line 2, expected screen, expected fields)
    ("Volume -28.75 dB", "PHONO           ", "normal", {"volume_db": -28.75, "input": "PHONO"}),
    ("Volume -15.00 dB", "TAPE/AUX        ", "normal", {"volume_db": -15.0, "input": "TAPE/AUX"}),
    ("Volume -28.75 dB", B * 10 + " " * 6, "volume", {"volume_db": -28.75}),
    ("Volume -27.75 dB", "PHONO           ", "unknown", {}),          # not a 1.25 step
    ("Volume -28.75 dB", "PHO             ", "unknown", {}),          # half-written screen
    ("Bass   2 dB     ", "       <>" + B + "      ", "bass", {"bass_db": 2}),
    ("Bass -10 dB     ", "  " + B * 5 + "<>       ", "bass", {"bass_db": -10}),
    ("Bass -10 dB     ", "   " + B * 4 + "<>       ", "unknown", {}),  # bar doesn't match
    ("Treble   0 dB   ", "       <>       ", "treble", {"treble_db": 0}),
    ("Balance <level> ", "       <>       ", "balance", {"balance": {"side": None, "db": 0.0}}),
    ("Balance -5.00 dB", "       <>" + B + "      ", "balance", {"balance": {"side": "R", "db": -5.0}}),
    ("Balance-10.00 dB", "     " + B * 2 + "<>       ", "balance", {"balance": {"side": "L", "db": -10.0}}),
    ("Balance -1.25 dB", "       <>       ", "balance", {"balance": {"side": None, "db": -1.25}}),
    ("   Loudness     ", " < OFF >   ON   ", "loudness", {"loudness": False}),
    ("   Speakers     ", "   OFF   < ON > ", "speakers", {"speakers": True}),
    ("    ACOUSTIC    ", "    SOLUTIONS   ", "boot", {}),
    ("Amplifier SP103 ", " SW version 1.0 ", "about", {"firmware": "1.0"}),
    ("                ", "                ", "unknown", {}),
]


def self_test():
    bad = 0
    for l1, l2, screen, values in CASES:
        got = parse(l1, l2)
        ok = got == (screen, values)
        bad += not ok
        print(("ok   " if ok else "FAIL "), repr(l1), repr(l2), "->", got)
    print(f"\n{len(CASES) - bad} of {len(CASES)} ok")
    bad += not standby_test()
    bad += not speakers_after_standby_test()
    return bad == 0


def speakers_after_standby_test():
    """Leaving standby, the amp comes back with speakers on, without showing that screen."""
    blank = " " * 16
    st = AmpState()
    st.update("   Speakers     ", " < OFF >   ON   ", 1)
    st.update("   Loudness     ", "   OFF   < ON > ", 2)
    st.update(blank, blank, 3)
    if st.speakers is not False or st.power != "standby":
        print("FAILED: speakers should stay OFF in standby", st.speakers, st.power)
        return False
    st.update("Volume -20.00 dB", "CD              ", 4)
    if st.speakers is not True or st.loudness is not True:
        print("FAILED: after standby", st.speakers, st.loudness)
        return False
    return True


def standby_test():
    """Blank screen = standby; the blank screen at power-on (with "Clear display") doesn't count."""
    blank, vol = " " * 16, ("Volume -20.00 dB", "DAB" + " " * 13)
    st, steps = AmpState(), []
    steps.append((st.update(blank, blank, 0, cleared=True), st.power, None, "powering on: blank with clear"))
    st.update("    ACOUSTIC    ", "   SOLUTIONS    ", 1)
    steps.append((True, st.power, "on", "boot screen: on"))
    st.update(*vol, 2)
    steps.append((st.update(blank, blank, 3), st.power, "standby", "blank without clear: standby"))
    steps.append((True, st.screen, "standby", "the screen is called standby"))
    steps.append((True, st.volume_db, -20.0, "the last volume is kept"))
    steps.append((not st.update(blank, blank, 4), st.power, "standby", "blank again: nothing changes"))
    st.update(blank, blank, 5, cleared=True)
    steps.append((True, st.power, "standby", "powering on again: not 'on' yet..."))
    st.update(*vol, 6)
    steps.append((True, st.power, "on", "...until the first screen"))
    bad = 0
    for changed, got, want, what in steps:
        ok = changed and got == want
        bad += not ok
        print(("ok   " if ok else "FAIL "), what, "->", got)
    return bad == 0


def screens(lcd):
    """The two lines of the LCD's memory, with the original codes (chr(0) = box)."""
    return ["".join(chr(lcd.ddram[base + (col + lcd.shift) % 40]) for col in range(16))
            for base in (0x00, 0x40)]


def replay(path, sem_rw):
    freq, pre, burst, by_number, by_name = hd.load_lac(path)
    sig = hd.pick_signals(by_number, by_name)
    events, _, _, _ = hd.decode(sig, freq, pre)
    if sem_rw:
        events = [(t, rs, 1 if (rs == 0 and full < 0x80) else 0, full, nib)
                  for t, rs, rw, full, nib in events]

    print(f"=== {path}")
    lcd = hd.Lcd()
    st = AmpState()
    pending = False

    def offer(t):
        l1, l2 = screens(lcd)
        if st.update(l1, l2, int(t / 1000)):
            d = st.to_dict()
            print(f"  {t / 1000:9.1f} ms  {d['lcd'][0]} | {d['lcd'][1]}  ->  "
                  + json.dumps({k: d[k] for k in ("screen", "volume_db", "input", "bass_db",
                                                    "treble_db", "balance", "loudness", "speakers",
                                                    "firmware") if d[k] is not None}))

    last_t = None
    for t, rs, rw, full, nib in events:
        if pending and last_t is not None and t - last_t > QUIET_US:
            offer(last_t)
            pending = False
        last_t = t
        if rw:
            continue                    # busy flag read: doesn't change the screen
        if rs:
            lcd.data(full)
        else:
            lcd.command(full)
        pending = True
    if pending:
        offer(last_t)                   # end of capture: the screen may be incomplete
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("capturas", metavar="captures", nargs="*")
    ap.add_argument("--no-rw", "--sem-rw", dest="sem_rw", action="store_true",
                    help="the RW wire failed in the capture (see hd44780_decode.py)")
    args = ap.parse_args()
    if not args.capturas:
        sys.exit(0 if self_test() else 1)
    for path in args.capturas:
        replay(path, args.sem_rw)


if __name__ == "__main__":
    main()
