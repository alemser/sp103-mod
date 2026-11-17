"""Listens to the amp's LCD bus with the PIO, never driving any signal onto it.

Wiring (the same as for the captures, docs/analyzer-wiring.md):

    GP2 = E   GP3 = RS   GP4 = RW   GP5..GP12 = D0..D7   (+ GND on LCD pin 1)

SAFETY RULE: GP2..GP12 receive 5 V from the amp and there are no series resistors.
They must NEVER be outputs driving 1: that would fight the controller.
Here they are all inputs. Future experiments may only PULL to 0
(output value fixed at 0, changing only the pin direction).

How it works: on each falling edge of E (when the LCD reads the byte), the PIO reads
the 11 wires and pushes the word into the FIFO. A DMA channel copies the FIFO, nonstop,
into a ring buffer in memory. So nothing is lost while Python is busy with Wi-Fi;
read() returns the new words (format in hd44780.py).
"""

import rp2
import uctypes
from array import array
from machine import Pin

BUS_BASE = 2                    # GP2: first bus wire (E)
BUS_PINS = 11                   # E, RS, RW, D0..D7
RING_BITS = 14                  # ring buffer of 2^14 bytes = 4096 words (about 30 screens)

# RP2350 addresses (datasheet, DMA and PIO sections).
_PIO_BASE = (0x50200000, 0x50300000, 0x50400000)
_RXF0 = 0x020                   # output (RX) FIFO of state machine 0; the others follow every 4
_DREQ_PIO_RX0 = (4, 12, 20)     # DMA request "the RX FIFO has data"
_ENDLESS = 0xF0000001           # TRANS_COUNT with MODE = 0xF: the DMA never stops (the count cannot be 0)


@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_LEFT)
def _sniff():
    # Noise filter: with long wires, the E edge "rings" and looks like an extra pulse. The amp's
    # real pulses last 10 µs or more (captures); the noise, 1 µs or less. A pulse only counts if
    # it stays at 1 for ~3 µs, followed by E at 0 for ~1.7 µs. (At 150 MHz; jmp_pin = E.)
    label("idle")
    wait(1, pin, 0)             # E rises
    set(x, 31)
    label("high")
    jmp(pin, "high_ok")
    jmp("idle")                 # fell too early: it was noise
    label("high_ok")
    jmp(x_dec, "high") [13]     # 32 x 15 cycles = 3.2 µs
    wait(0, pin, 0)             # E falls: the LCD read the byte; RS, RW and data are still stable
    in_(pins, 11)
    push(noblock)               # FIFO full (should not happen, the DMA drains it): the word is lost
    label("low_restart")
    wait(0, pin, 0)
    set(x, 31)
    label("low")
    jmp(pin, "low_restart")     # rose again right away: noise on the falling edge, wait for it to fall again
    jmp(x_dec, "low") [6]       # 32 x 8 cycles = 1.7 µs


class Sniffer:
    def __init__(self, sm_id=0):
        # sm_id 0 = PIO0, state machine 0. (The Wi-Fi chip uses state machine 8, on PIO2.)
        for n in range(BUS_BASE, BUS_BASE + BUS_PINS):
            Pin(n, Pin.IN, pull=None)   # input only, no pull (the amp already sets every level)

        size = 1 << RING_BITS
        # The ring DMA needs a buffer aligned to its size: we reserve twice as much and use
        # the aligned part.
        self._buf = array("I", bytes(2 * size))
        start = uctypes.addressof(self._buf)
        self._first = ((-start) % size) // 4
        self._base = start + self._first * 4
        self._mask = size // 4 - 1
        self._rd = 0

        self.sm = rp2.StateMachine(sm_id, _sniff, freq=150_000_000, in_base=Pin(BUS_BASE),
                                   jmp_pin=Pin(BUS_BASE))
        pio, sm = divmod(sm_id, 4)
        self.dma = rp2.DMA()
        ctrl = self.dma.pack_ctrl(size=2, inc_read=False, inc_write=True,
                                  ring_size=RING_BITS, ring_sel=True,
                                  treq_sel=_DREQ_PIO_RX0[pio] + sm)
        self.dma.config(read=_PIO_BASE[pio] + _RXF0 + 4 * sm, write=self._base,
                        count=_ENDLESS, ctrl=ctrl, trigger=True)
        self.sm.active(1)

    def read(self):
        """The words that arrived since the last call (generator)."""
        wr = ((self.dma.write - self._base) >> 2) & self._mask
        buf, first, mask, rd = self._buf, self._first, self._mask, self._rd
        while rd != wr:
            yield buf[first + rd]
            rd = (rd + 1) & mask
        self._rd = rd

    def stop(self):
        self.sm.active(0)
        self.dma.active(0)
        self.dma.close()
