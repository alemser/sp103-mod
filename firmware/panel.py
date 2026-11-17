"""Presses the Function button on the amp's front panel, from the inside.

Wiring (docs/proxy-ligacao.md):

    GP0 = controller leg 6     GP1 = controller leg 13

The controller pulses leg 6 and reads leg 13: with the button pressed, leg 13 falls together with leg 6
(capture from 2026-11-06). The PIO imitates that: inside each long pulse on GP0, it pulls GP1 to 0.

SAFETY RULE: GP0 is never an output. GP1 is never driven to 1: its output value stays 0 and only the
direction changes, at 2 mA. Leg 13 rises through a 4.7 kΩ resistor, so pulling it costs about 1 mA.

On about 1 click in 8, the amp also selects the PHONO input. control.py corrects that.
"""

import time

import rp2
from machine import Pin, mem32

PIN_SCAN, PIN_READ = 0, 1
PRESS_MS = 60
_PADS_BANK0 = 0x40038000
_DRIVE_MASK = 0x3 << 4


@rp2.asm_pio(set_init=rp2.PIO.IN_LOW)
def _mirror():
    # At 10 MHz. Leg 6 pulses last 25 to 30 µs, with some of 5 to 10 µs. Only the long ones count, and
    # leg 13 rises before the end of the pulse.
    wait(0, gpio, 0)            # leg 6 at 0
    set(x, 31)
    label("settle")
    jmp(x_dec, "settle") [3]    # 12.8 µs
    jmp(pin, "done")            # already rose: short pulse
    set(pindirs, 1)             # leg 13 at 0
    set(x, 24)
    label("hold")
    jmp(x_dec, "hold") [3]      # 10 µs
    set(pindirs, 0)
    label("done")
    wait(1, gpio, 0)


class Panel:
    def __init__(self, sm_id=6):
        # sm_id 6 = PIO1, state machine 2 (0 is busy.py's and 1 is ir.py's).
        Pin(PIN_SCAN, Pin.IN, pull=None)
        Pin(PIN_READ, Pin.IN, pull=None)
        self.sm = rp2.StateMachine(sm_id, _mirror, freq=10_000_000, set_base=Pin(PIN_READ),
                                   jmp_pin=Pin(PIN_SCAN))
        self.sm.exec("set(pins, 0)")
        self.sm.exec("set(pindirs, 0)")
        pad = _PADS_BANK0 + 4 + 4 * PIN_READ
        mem32[pad] = mem32[pad] & ~_DRIVE_MASK & ~1     # 2 mA, slow edge

    def press(self):
        self.sm.active(1)
        time.sleep_ms(PRESS_MS)
        self.sm.active(0)
        self.sm.exec("set(pindirs, 0)")
