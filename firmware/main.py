"""Runs by itself every time the Pico starts (MicroPython runs main.py at boot).

Today: the amp listener (escuta.py, stage 4). The bench demo, with the fake amp, is
still available: .venv/bin/mpremote run firmware/bancada_wifi.py
To stop it and get back to the computer, use mpremote: it interrupts the program
(Ctrl-C) before each command.

Updates over Wi-Fi (ota.py, tools/enviar.py): this file is the "gatekeeper" that
restores the previous version if the new one fails. So it uses NO other file of the
project and can only be replaced over USB (ota.py refuses it).

    update.json = {"state": "trial", "boots": 0}   a new version, still on trial
    1st boot of the new version: boots becomes 1 and a timer gives the program
       TRIAL_S seconds to call ota.confirm() (state becomes "ok"). If it doesn't, the Pico restarts.
    Next boot still on "trial" (hung, crashed or the timer ran out): go back.
    "rollback" (asked for by the page or by enviar.py): go back too.
Going back = copying back the old/ folder (the whole previous version, kept by ota.py).
"""

import os
import sys
import json
import time
import machine

MARKER = "update.json"
OLD = "old"
TRIAL_S = 180               # time for the new version to prove healthy (see escuta.py)
_timer = None


def _marker():
    try:
        with open(MARKER) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save(m):
    with open(MARKER, "w") as f:
        json.dump(m, f)


def _restore():
    """Puts back the version kept in old/. Safe to repeat (if the power goes midway)."""
    old = os.listdir(OLD)
    for name in os.listdir():
        if name.endswith(".py") and name != "main.py" and name not in old:
            os.remove(name)                 # a file that only existed in the new version
    buf = bytearray(1024)
    for name in old:
        with open(OLD + "/" + name, "rb") as src, open(name, "wb") as dst:
            while True:
                n = src.readinto(buf)
                if not n:
                    break
                dst.write(buf[:n])


def _check_update():
    global _timer                           # kept here so the garbage collector doesn't free it
    m = _marker()
    if not m:
        return
    if m["state"] == "rollback" or (m["state"] == "trial" and m.get("boots", 0) >= 1):
        why = "requested" if m["state"] == "rollback" else "the new version did not confirm"
        print("update: going back to the previous version (%s)" % why)
        _restore()
        _save({"state": "rolled_back", "why": why, "version": m.get("version")})
    elif m["state"] == "trial":
        m["boots"] = 1
        _save(m)
        print("update: new version on trial, %d s to confirm" % TRIAL_S)

        def deadline(t):
            if (_marker() or {}).get("state") == "trial":
                machine.reset()             # didn't confirm: the next boot goes back
        _timer = machine.Timer(period=TRIAL_S * 1000, mode=machine.Timer.ONE_SHOT,
                               callback=deadline)


try:
    _check_update()
except Exception as e:
    sys.print_exception(e)          # no old/ or a flash problem: carry on with what there is

try:
    import escuta                   # noqa: F401  (the program runs when imported)
except Exception as e:
    # Any error (Wi-Fi down, for example): show it and try again in 30 s.
    # On a version on trial, this restart makes _check_update() go back to the previous one.
    sys.print_exception(e)
    try:
        from lcd1602 import Lcd1602
        Lcd1602().show("Error, rebooting", str(e)[:16])
    except Exception:
        pass
    time.sleep(30)
    machine.reset()
