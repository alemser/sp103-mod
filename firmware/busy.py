"""Answers the amp's controller in place of the display: "free" (busy flag = 0) on every read.

With the display disconnected from the controller (option 3b, docs/proxy-ligacao.md), nobody
else answers the reads. The controller reads the busy flag before each command and each
character and, to do so, releases only D7, which the 4.7 kΩ resistor pulls to 1 = "busy".
With no answer, it asks again forever (docs/descobertas-protocolo.md).

On each read (RW = 1 at the rising edge of E), the PIO pulls D7 (GP12) to 0 until E falls.

SAFETY RULE (the same as sniffer.py's): GP12 is NEVER driven to 1. Its output value stays
0 (set_init and exec below) and only the direction changes. D7 is on the controller's P0, which
only rises through the pull-up: pulling it to 0 is always safe (~1 mA). Output at the lowest drive strength (2 mA).

Create AFTER the Sniffer: the Sniffer sets GP2..GP12 as plain inputs (Pin.IN), and that
would take GP12 away from the PIO.
"""

import rp2
from machine import Pin, mem32

E_PIN, RW_PIN, D7_PIN = 2, 4, 12
_PADS_BANK0 = 0x40038000
_DRIVE_MASK = 0x3 << 4


@rp2.asm_pio(set_init=rp2.PIO.IN_LOW)
def _answer():
    # jmp_pin = RW; set_base = D7. At the rising edge of E, RS and RW are already in place (captures).
    # E is given as a number (2 = E_PIN): inside here asm_pio hides the module's variables.
    label("top")
    wait(1, gpio, 2)            # E rises
    jmp(pin, "read")            # RW = 1: it is a read
    wait(0, gpio, 2)            # write: just wait for the pulse to end
    jmp("top")
    label("read")
    set(pindirs, 1)             # D7 at 0 = "free"
    wait(0, gpio, 2)            # E falls: the controller has read it
    set(pindirs, 0)             # release D7 (the amp's pull-up takes it back to 1)


class Responder:
    def __init__(self, sm_id=4):
        # sm_id 4 = PIO1, state machine 0 (the sniffer uses PIO0; Wi-Fi, PIO2).
        self.sm = rp2.StateMachine(sm_id, _answer, freq=150_000_000,
                                   set_base=Pin(D7_PIN), jmp_pin=Pin(RW_PIN))
        self.sm.exec("set(pins, 0)")
        self.sm.exec("set(pindirs, 0)")
        pad = _PADS_BANK0 + 4 + 4 * D7_PIN
        mem32[pad] = mem32[pad] & ~_DRIVE_MASK & ~1     # 2 mA, slow edge
        self.sm.active(1)
