"""Simple driver for a 16x2 LCD (HD44780) in 4-bit mode, write only (RW on GND).

Wiring: RS=GP16, E=GP17, D4..D7=GP18..GP21, on the amp's display (docs/installation.md)
or on the bench spare (docs/bench-wiring.md).
Since RW is on GND, the busy flag cannot be read: we wait the maximum time
for each command (HD44780 datasheet).
"""

import time
from machine import Pin


class Lcd1602:
    def __init__(self, rs=16, e=17, d4=18):
        self.rs = Pin(rs, Pin.OUT, value=0)
        self.e = Pin(e, Pin.OUT, value=0)
        self.d = [Pin(d4 + i, Pin.OUT, value=0) for i in range(4)]
        self.reset()

    # --- low level ---------------------------------------------------------

    def _nibble(self, n):
        for i in range(4):
            self.d[i].value((n >> i) & 1)
        self.e.value(1)
        time.sleep_us(1)                # the E pulse needs at least 450 ns
        self.e.value(0)
        time.sleep_us(1)

    def _byte(self, b, rs):
        self.rs.value(rs)
        self._nibble(b >> 4)
        self._nibble(b & 0x0F)
        time.sleep_us(50)               # most commands take 37 µs

    def command(self, b):
        self._byte(b, 0)
        if b in (0x01, 0x02):           # Clear and Home take 1.52 ms
            time.sleep_ms(2)

    def data(self, b):
        self._byte(b, 1)

    def reset(self):
        """Restarts the display. Also fixes the 4-bit mode "garbled text":
        if a bad contact makes the display lose half a byte, it keeps pairing
        the wrong halves until it is restarted. This sequence resyncs it."""
        time.sleep_ms(50)
        self.on = True
        self.resync()
        self.command(0x01)              # clear

    def resync(self):
        """The part of reset() that resyncs the 4-bit mode, without clearing the screen.
        In the middle of the sequence the display only gets configuration and address
        commands; the caller rewrites the text and the custom characters afterwards."""
        # Datasheet sequence to enter 4-bit mode, starting from any state.
        self.rs.value(0)
        for wait_us in (4500, 150, 150):
            self._nibble(0x3)
            time.sleep_us(wait_us)
        self._nibble(0x2)               # now in 4 bits
        time.sleep_us(150)
        self.command(0x28)              # 4 bits, 2 lines, 5x8
        self.command(0x0C if self.on else 0x08)   # display on (or not), no cursor
        self.command(0x06)              # writes left to right

    def display(self, on):
        self.on = on
        self.command(0x0C if on else 0x08)

    # --- high level --------------------------------------------------------

    def define_char(self, code, rows):
        """Stores a custom character (code 0 to 7, 8 rows of 5 dots)."""
        self.command(0x40 | (code << 3))
        for r in rows:
            self.data(r)
        self.command(0x80)              # back to DDRAM

    def write_line(self, row, text, old=None):
        """Writes a 16-position line (padded with spaces).

        old = what is already on that display line: sends only the positions that changed (each
        byte costs about 100 µs with the loop stalled; in the VU, few cells change per frame).
        Without old, writes all 16."""
        text = (text + " " * 16)[:16]
        base = 0x80 | (0x40 if row else 0x00)
        if old is None or len(old) != 16:
            self.command(base)
            for c in text:
                self.data(ord(c))
            return
        at = -1                         # where the display cursor is (-1 = unknown)
        for col in range(16):
            if text[col] == old[col]:
                continue
            if at >= 0 and col - at == 1:
                self.data(ord(text[at]))    # a single unchanged cell in between: rewriting costs the same as skipping
            elif col != at:
                self.command(base + col)
            self.data(ord(text[col]))
            at = col + 1

    def show(self, line1, line2):
        self.write_line(0, line1)
        self.write_line(1, line2)
