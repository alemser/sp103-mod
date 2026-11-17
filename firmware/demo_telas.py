"""Bench, stage 1: shows every SP103 screen on the spare display, one every 2 s.

Run from the computer:  .venv/bin/mpremote run firmware/demo_telas.py
(first copy the modules: .venv/bin/mpremote cp firmware/lcd1602.py firmware/sp103_screens.py :)
"""

import time
import sp103_screens as s
from lcd1602 import Lcd1602

lcd = Lcd1602()

SCREENS = [
    ("welcome", s.boot()),
    ("model", s.about()),
    ("normal", s.normal(-28.75, "PHONO")),
    ("volume", s.volume_bar(-28.75)),
    ("bass", s.tone("Bass", 2)),
    ("bass", s.tone("Bass", -10)),
    ("treble", s.tone("Treble", 0)),
    ("balance", s.balance(None, 0)),
    ("balance R", s.balance("R", -10.0)),
    ("balance L", s.balance("L", -10.0)),
    ("loudness", s.choice("Loudness", False)),
    ("speakers", s.choice("Speakers", True)),
    ("CGRAM 0-7", ("".join(chr(i) for i in range(8)), "Turntable")),
]

while True:
    for name, (l1, l2) in SCREENS:
        print(name)
        # Restarts on every screen: if a bad contact garbles the display, the next screen comes out right.
        lcd.reset()
        for code, rows in enumerate(s.CGRAM):
            lcd.define_char(code, rows)
        lcd.show(l1, l2)
        time.sleep(2)
