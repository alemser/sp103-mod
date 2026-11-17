"""VU meter on the amp's display: the L and R channels, with the peak mark, in four layouts.

Frames come from sp103-vu-relay (relay/main.go), which forwards the groove-detector's VU
over UDP. The Pico subscribes every 2 s ("SUB1"); each frame is 12 bytes:

    "VU" 0x01 flags  float32 L  float32 R      (RMS 0..1; flags: bit 0 = music playing)

Layouts (names.py "layout"); each has its own 8 custom characters (CGRAM), in Vu.glyphs,
and on leaving proxy.py writes the controller's back:

- "bars", thin bars: line 1 = L, line 2 = R. Column 0 shows the letter; columns 1..15
  are the bar, 5 pixel columns each: 75 steps from floor to top. The scale ticks sit at
  -30, -20, -10, -6 and -3 dB from the top.
- "deck", cassette deck: like "bars", but with two separate segments per cell (30 steps);
  those in the last 3 cells are taller, in place of the red zone. The peak is a single
  lit segment; clip lights the last cell.
- "scale", printed scale: L and R share line 1 (L in the top half of each cell, R in the
  bottom; 2 segments per cell, 32 steps). Line 2 is the ruler, in dB below the top. The
  peak is a single lit segment; on clip, the ruler's "0" becomes a full block (ROM
  character 255, outside the 8 custom characters).
- "kx393", the Yamaha KX-393 meter: L and R share line 1, no letters, one segment per
  cell (16 steps) on the deck's scale, which is not linear: -30 to +8 dB, in steps of 2
  near 0. The deck's 0 sits KX_ZERO dB below the top, and the segments above it are
  taller, in place of the red. Line 2 is the deck's ruler. The peak is a single lit
  segment; clip lights the last one.

Scale (names.py): REC OUT arrives at very different levels depending on the source
(measured on 2026-10-29 on the Pi 5: DAB near -30 dBFS, vinyl near -11). With the
automatic scale, the top sits AUTO_HEADROOM dB above the loudest frame: it rises at once
and, with music, falls at AUTO_FALL_DB_S; the floor sits AUTO_SPAN dB below the top. The
settings only offer the automatic one; the manual one (fixed floor and top, "auto": False)
is kept for the tests, which need a still scale.

The bar rises at once and a full bar empties in FALL_S. The peak holds for 1 s and falls
the whole scale in PEAK_FALL_S. Above -1 dBFS (real clipping, not the top) the clip
lights for 1 s.
"""

import math
import socket
import struct
import time

import udp

PORT = 7091
SUBSCRIBE = b"SUB1"
SUBSCRIBE_MS = 2000             # the relay forgets the subscription after 6 s
STALE_MS = 1000                 # no frame for 1 s: back to the amp screen
FALL_S = 0.5                    # a full bar empties in 0.5 s (proportional to the scale)
PEAK_HOLD_MS = 1000
PEAK_FALL_S = 1.0
# Music varies little from one frame to the next (vinyl on 2026-10-29: 90 % of frames
# within 7 dB). With 20 dB, like a needle VU, and 5 dB of headroom, the bar stays between
# half and 3/4 and moves; with 30 dB and 3 dB it sat still near the end.
AUTO_SPAN = 20                  # automatic scale: floor to top
AUTO_HEADROOM = 5               # the top sits 5 dB above the loudest frame
AUTO_FALL_DB_S = 1              # and falls 1 dB/s with music (from -3 to -27 in 24 s)
AUTO_TOP = (-40, 0)             # limits of the automatic top
CLIP_DB = -1
CLIP_MS = 1000
STEPS = 75                      # 15 cells x 5 pixel columns
TICKS_DB = (-30, -20, -10, -6, -3)   # below the top
SILENT_DB = -100.0
FLAG_PROGRAMME = 1
LAYOUTS = ("bars", "deck", "scale", "kx393")


def _rows(bits, rows):
    return bytes([bits if r in rows else 0 for r in range(8)])


_BAR = (1, 2, 3, 4, 5, 6)       # the bar leaves the top and bottom pixel rows free
GLYPHS = b"".join((
    _rows(0x10, _BAR),          # 0: 1 column
    _rows(0x18, _BAR),          # 1: 2 columns
    _rows(0x1C, _BAR),          # 2: 3 columns
    _rows(0x1E, _BAR),          # 3: 4 columns
    _rows(0x1F, _BAR),          # 4: full cell
    _rows(0x04, range(8)),      # 5: peak mark, taller than the bar
    _rows(0x04, (7,)),          # 6: scale tick, at the bottom of the empty bar
    _rows(0x1F, range(8)),      # 7: clip, in the last cell
))
FULL, PEAK, TICK, CLIP = 4, 5, 6, 7

DECK_GLYPHS = b"".join((
    _rows(0x18, _BAR),          # 0: left segment
    _rows(0x1B, _BAR),          # 1: both segments
    _rows(0x03, _BAR),          # 2: the right one (lone peak)
    _rows(0x18, range(8)),      # 3..5: the same in the hot zone, taller
    _rows(0x1B, range(8)),
    _rows(0x03, range(8)),
    _rows(0x04, (7,)),          # 6: scale tick
    bytes(8),                   # 7: unused
))
DECK_HOT, DECK_TICK = 12, 6     # from cell 12 on: hot zone

# Printed scale: state of each channel in a cell = 0 off, 1 only the left segment,
# 2 both. The character for the pair (l, r) is code 3 * l + r - 1.
_HALF = (0, 0x18, 0x1B)
SCALE_GLYPHS = b"".join(
    bytes([_HALF[l] if y < 3 else _HALF[r] if 4 <= y < 7 else 0 for y in range(8)])
    for l in range(3) for r in range(3) if l or r)
# In priority order: a mark that does not fit without touching another is left out.
SCALE_MARKS = ((0, "0"), (-20, "20"), (-10, "10"), (-30, "30"), (-6, "6"), (-3, "3"))
BLOCK = chr(255)                # full block from the HD44780 ROM

# KX-393: the steps of the deck's scale, in dB from its 0 (one per cell).
KX_DB = (-30, -25, -20, -17, -14, -12, -10, -8, -6, -4, -2, 0, 2, 4, 6, 8)
KX_ZERO = -10                   # the deck's 0, below the top: the loudest passages reach +4
KX_RULER = "30 17 10 4 0 4 8"   # each number starts under its segment


def _kx(left, right, hot):
    """One KX-393 segment: L on the top rows, R on the bottom ones; the hot one is taller."""
    rows_l, rows_r = ((0, 1, 2), (5, 6, 7)) if hot else ((1, 2), (5, 6))
    return bytes([0x1E if (left and y in rows_l) or (right and y in rows_r) else 0 for y in range(8)])


# Code = 3 if hot + 0 L only, 1 R only, 2 both; 6 and 7 unused.
KX_GLYPHS = b"".join(_kx(l, r, hot) for hot in (0, 1) for l, r in ((1, 0), (0, 1), (1, 1))) + bytes(16)


def db(rms):
    return 20 * math.log10(rms) if rms > 1e-5 else SILENT_DB


class Meter:
    """One channel: level with slow fall, peak hold and clip."""

    def __init__(self):
        self.level = SILENT_DB
        self.peak = SILENT_DB
        self.hold_until = 0
        self.clip_until = 0
        self.clip = False

    def feed(self, value_db, dt_ms, now, span):
        if value_db >= self.level:
            self.level = value_db
        else:
            self.level = max(value_db, self.level - span / FALL_S * dt_ms / 1000)
        if self.level >= self.peak:
            self.peak = self.level
            self.hold_until = time.ticks_add(now, PEAK_HOLD_MS)
        elif time.ticks_diff(now, self.hold_until) > 0:
            self.peak = max(self.level, self.peak - span / PEAK_FALL_S * dt_ms / 1000)
        if value_db > CLIP_DB:
            self.clip_until = time.ticks_add(now, CLIP_MS)
        self.clip = time.ticks_diff(self.clip_until, now) > 0


class Vu:
    def __init__(self):
        self.on = False
        self.auto = True
        self.floor = -40
        self.top = 0
        self.addr = None
        self.sock = None
        self._poll = None
        self.last_sub = None
        self.last_frame = None
        self.programme = False
        self.frames = 0
        self.error = None               # proxy.py turns the VU off if it raises an error
        self.L = Meter()
        self.R = Meter()
        self.layout = "bars"
        self.glyphs = GLYPHS
        self._ticks = ()
        self._ruler = " " * 16

    def configure(self, cfg):
        """cfg = names.json "vu": {"on", "auto", "layout", "relay"} (+ "floor" and "top" without "auto")."""
        self.on = cfg["on"]
        self.layout = cfg["layout"]
        self.glyphs = {"bars": GLYPHS, "deck": DECK_GLYPHS, "scale": SCALE_GLYPHS,
                       "kx393": KX_GLYPHS}[self.layout]
        self.error = None
        self.auto = cfg["auto"]
        if self.auto:
            # The top starts low: the first frame with music moves it into place.
            self.top = AUTO_TOP[0]
            self.floor = self.top - AUTO_SPAN
        else:
            self.floor = cfg["floor"]
            self.top = cfg["top"]
        # The ticks and the ruler sit at fixed distances from the top: on the automatic
        # scale, which only shifts, their cells do not change.
        per_cell = 2 if self.layout == "deck" else 5
        steps = 15 * per_cell
        self._ticks = tuple(c for c in ((self._px(self.top + d, steps) - 1) // per_cell
                                        for d in TICKS_DB if self.top + d > self.floor) if c >= 0)
        span = self.top - self.floor
        ruler = [" "] * 18              # with one empty slot on each side
        for d, text in SCALE_MARKS:
            if d < -span:
                continue
            col = 1 + min(16 - len(text), int((d + span) * 15 / span + 0.5))
            if all(c == " " for c in ruler[col - 1:col + len(text) + 1]):
                ruler[col:col + len(text)] = list(text)   # MicroPython only accepts a list here
        self._ruler = "".join(ruler[1:17])
        addr = (cfg["relay"], PORT)
        if addr != self.addr or not self.on:
            self.close()
        self.addr = addr
        self.last_sub = None            # subscribe right away

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
            self._poll = None
        self.last_frame = None

    def _px(self, value_db, steps=STEPS):
        x = round((value_db - self.floor) * steps / (self.top - self.floor))
        return 0 if x < 0 else steps if x > steps else x

    def poll(self, now):
        """Request and read frames (without waiting). True if a new frame arrived."""
        if not self.on:
            return False
        if self.sock is None:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setblocking(False)
            self._poll = udp.poller(self.sock)
        if self.last_sub is None or time.ticks_diff(now, self.last_sub) >= SUBSCRIBE_MS:
            self.last_sub = now
            try:
                self.sock.sendto(SUBSCRIBE, self.addr)
            except OSError:
                pass                    # no Wi-Fi yet: try again in 2 s
        new = False
        while udp.ready(self._poll):
            try:
                data = self.sock.recv(32)
            except OSError:
                break                   # nothing in the queue
            if len(data) != 12 or data[:3] != b"VU\x01":
                continue
            _, _, flags, left, right = struct.unpack("<2sBBff", data)
            dt = 46 if self.last_frame is None else \
                min(200, max(10, time.ticks_diff(now, self.last_frame)))
            self.programme = bool(flags & FLAG_PROGRAMME)
            l_db, r_db = db(left), db(right)
            if self.auto and self.programme:
                self._follow(max(l_db, r_db), dt)
            span = self.top - self.floor
            self.L.feed(l_db, dt, now, span)
            self.R.feed(r_db, dt, now, span)
            self.last_frame = now
            self.frames += 1
            new = True
        return new

    def _follow(self, value_db, dt_ms):
        """Automatic scale: the top rises at once to frame + headroom and falls slowly."""
        want = value_db + AUTO_HEADROOM
        top = want if want > self.top else max(want, self.top - AUTO_FALL_DB_S * dt_ms / 1000)
        self.top = min(AUTO_TOP[1], max(AUTO_TOP[0], top))
        self.floor = self.top - AUTO_SPAN

    def active(self, now):
        """On, with frames arriving and music playing."""
        return self.on and self.programme and self.last_frame is not None \
            and time.ticks_diff(now, self.last_frame) < STALE_MS

    def _bars(self, label, m):
        lv, pk = self._px(m.level), self._px(m.peak)
        peak_cell = (pk - 1) // 5 if pk > lv else -1
        out = [label]
        for c in range(15):
            filled = lv - 5 * c
            if c == 14 and m.clip:
                out.append(chr(CLIP))
            elif filled >= 5:
                out.append(chr(FULL))
            elif filled > 0:
                out.append(chr(filled - 1))
            elif c == peak_cell:
                out.append(chr(PEAK))
            elif c in self._ticks:
                out.append(chr(TICK))
            else:
                out.append(" ")
        return "".join(out)

    def _deck(self, label, m):
        lv, pk = self._px(m.level, 30), self._px(m.peak, 30)
        if pk <= lv:
            pk = 0
        out = [label]
        for c in range(15):
            a = lv >= 2 * c + 1 or pk == 2 * c + 1 or (c == 14 and m.clip)
            b = lv >= 2 * c + 2 or pk == 2 * c + 2 or (c == 14 and m.clip)
            hot = 3 if c >= DECK_HOT else 0
            if a or b:
                out.append(chr(hot + (1 if a and b else 0 if a else 2)))
            else:
                out.append(chr(DECK_TICK) if c in self._ticks else " ")
        return "".join(out)

    @staticmethod
    def _half(lv, pk, c):
        """State of one channel in cell c of the printed scale (0, 1 or 2)."""
        s = lv - 2 * c
        s = 0 if s < 0 else 2 if s > 2 else s
        if s or pk <= lv or (pk - 1) // 2 != c:
            return s
        return 1 if pk % 2 else 2       # lone peak: only the right one has no character

    def _scale(self):
        l, r = self._px(self.L.level, 32), self._px(self.R.level, 32)
        pl, pr = self._px(self.L.peak, 32), self._px(self.R.peak, 32)
        out = []
        for c in range(16):
            a, b = self._half(l, pl, c), self._half(r, pr, c)
            out.append(chr(3 * a + b - 1) if a or b else " ")
        ruler = self._ruler
        if self.L.clip or self.R.clip:
            ruler = ruler[:15] + BLOCK
        return "".join(out), ruler

    def _kx_lit(self, m):
        """The lit segments of one channel on the KX-393: the bar, the lone peak and the clip."""
        zero = self.top + KX_ZERO
        lv = sum(1 for d in KX_DB if m.level >= zero + d)
        pk = sum(1 for d in KX_DB if m.peak >= zero + d)
        last = len(KX_DB) - 1
        return [i < lv or (pk > lv and i == pk - 1) or (i == last and m.clip) for i in range(last + 1)]

    def _kx393(self):
        l, r = self._kx_lit(self.L), self._kx_lit(self.R)
        out = []
        for i, d in enumerate(KX_DB):
            if l[i] or r[i]:
                out.append(chr((3 if d > 0 else 0) + (2 if l[i] and r[i] else 1 if r[i] else 0)))
            else:
                out.append(" ")
        return "".join(out), KX_RULER

    def lines(self):
        if self.layout == "scale":
            return self._scale()
        if self.layout == "kx393":
            return self._kx393()
        row = self._deck if self.layout == "deck" else self._bars
        return row("L", self.L), row("R", self.R)

    def status(self, now):
        age = None if self.last_frame is None else time.ticks_diff(now, self.last_frame)
        return {"on": self.on, "auto": self.auto, "layout": self.layout, "floor": round(self.floor), "top": round(self.top),
                "frames": self.frames, "last_frame_ms": age,
                "music": self.programme, "showing": self.active(now), "error": self.error}
