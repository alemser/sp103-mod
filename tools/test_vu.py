#!/usr/bin/env python3
"""Tests the display's VU (firmware/vu.py) and its settings (names.py) on the computer.

With a fake clock and socket: the bar's fall, the peak hold, the clip, drawing the
two lines, the request to the relay and "only with music".

    python3 tools/test_vu.py
"""

import os
import struct
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))

import time as real_time   # noqa: E402

fake_time = types.ModuleType("time")
for k in dir(real_time):
    if not k.startswith("__"):
        setattr(fake_time, k, getattr(real_time, k))
fake_time.ticks_add = lambda a, b: a + b
fake_time.ticks_diff = lambda a, b: a - b
sys.modules["time"] = fake_time

import names   # noqa: E402
import vu      # noqa: E402

sys.modules["time"] = real_time
fails = 0


def check(ok, what):
    global fails
    fails += not ok
    print("%-5s %s" % ("ok" if ok else "FAIL", what))


class FakeSocket:
    """The relay: keeps the requests and delivers the queued frames."""
    def __init__(self, *a):
        self.sent, self.queue, self.closed = [], [], False

    def setblocking(self, flag):
        pass

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def recv(self, n):
        if not self.queue:
            raise OSError(11)           # EAGAIN, like MicroPython with no data
        return self.queue.pop(0)

    def close(self):
        self.closed = True


vu.socket = types.SimpleNamespace(socket=FakeSocket, AF_INET=2, SOCK_DGRAM=2)


def frame(l_db, r_db, music=True):
    rms = lambda d: 10 ** (d / 20)
    return struct.pack("<2sBBff", b"VU", 1, 3 if music else 2, rms(l_db), rms(r_db))


def cfg(**kw):
    c = {"on": True, "auto": False, "floor": -40, "top": 0, "layout": "bars", "relay": "192.168.178.105"}
    c.update(kw)
    return c


# --- names.py: the VU settings ---------------------------------------
default = names.validate({})["vu"]
check(default == {"on": False, "auto": True, "layout": "bars", "relay": ""},
      "default: VU off, automatic scale, thin bars, no board chosen")
old = names.validate({"vu": {"on": True, "auto": False, "floor": -45, "top": -20,
                             "relay": "192.168.178.105"}})["vu"]
check(old == {"on": True, "auto": True, "layout": "bars", "relay": "192.168.178.105"},
      "old names.json with the manual scale: accepted, and the scale becomes automatic")
check(names.validate({"vu": {"on": False}})["inputs"] == {}, "just 'vu' doesn't turn into the old format")
for bad, what in (({"on": "yes"}, "non-boolean on"), ({"relay": "placa.local"}, "name instead of IP"),
                  ({"relay": "192.168.1.300"}, "invalid IP"), ({"on": True}, "VU on without a source")):
    try:
        names.validate({"vu": bad})
        check(False, "refuses: " + what)
    except ValueError:
        check(True, "refuses: " + what)

# --- Meter: fall, peak, clip ---------------------------------------------
m = vu.Meter()
m.feed(-10, 46, 0, 40)
check(m.level == -10 and m.peak == -10, "the bar rises at once")
m.feed(-60, 250, 250, 40)
check(abs(m.level - (-30)) < 1e-6, "40 dB scale: falls 80 dB/s (0.25 s: from -10 to -30)")
m.feed(-60, 250, 500, 40)
check(abs(m.level - (-50)) < 1e-6, "the full bar empties in 0.5 s")
check(m.peak == -10, "the peak holds for up to 1 s")
m.feed(-60, 500, 1500, 40)
check(abs(m.peak - (-30)) < 1e-6, "after 1 s the peak falls the whole scale in 1 s")
m.feed(-0.5, 46, 2046, 40)
check(m.clip, "above -1 dBFS: clip")
m.feed(-30, 46, 3100, 40)
check(not m.clip, "the clip goes off after 1 s")

# --- Vu: lines ---------------------------------------------------------------
v = vu.Vu()
v.configure(cfg())
v.L.level, v.L.peak = -20, -10        # half scale, peak at 3/4
v.R.level = v.R.peak = vu.SILENT_DB
l1, l2 = v.lines()
check(len(l1) == len(l2) == 16, "two lines of 16 cells")
check(l1[0] == "L" and l2[0] == "R", "column 0: L and R")
px = v._px(-20)                       # 38 of 75 steps: 7 full cells + 3 columns
check(l1[1:8] == chr(vu.FULL) * 7 and l1[8] == chr(2), "-20 dB of -40: 7 full and one of 3 columns (%d px)" % px)
check(l1.index(chr(vu.PEAK)) == 1 + (v._px(-10) - 1) // 5, "the peak mark in the -10 dB cell")
check(chr(vu.TICK) in l2 and chr(vu.FULL) not in l2, "silent channel: only the scale marks")
v.configure(cfg(floor=-20))
check(v._px(-20) == 0 and v._px(0) == 75, "floor -20: the scale goes from -20 to 0")
check(all(c >= 0 for c in v._ticks) and len(v._ticks) == 3, "floor -20: only the -10, -6 and -3 marks")
v.configure(cfg(floor=-45, top=-20))
check(v._px(-45) == 0 and v._px(-20) == 75 and v._px(-10) == 75, "top -20: the bar fills at -20 dBFS")
check(v._ticks == tuple((v._px(-20 + d) - 1) // 5 for d in (-20, -10, -6, -3)), "top -20: marks at -20..-3 dB from the top")
check(all(len(g) == 64 for g in (vu.GLYPHS, vu.DECK_GLYPHS, vu.SCALE_GLYPHS, vu.KX_GLYPHS)), "8 glyphs of 8 rows")
check(names.VU_LAYOUTS == vu.LAYOUTS, "names.py and vu.py know the same layouts")
check(names.validate({})["vu"]["layout"] == "bars", "default layout: thin bars")
check(names.validate({"vu": {"layout": "deck"}})["vu"]["layout"] == "deck", "layout configurable")
try:
    names.validate({"vu": {"layout": "needle"}})
    check(False, "refuses a layout that doesn't exist")
except ValueError:
    check(True, "refuses a layout that doesn't exist")

# --- Vu: cassette deck -------------------------------------------------------
v = vu.Vu()
v.configure(cfg(layout="deck"))
check(v.glyphs is vu.DECK_GLYPHS, "deck: the deck glyphs")
v.L.level, v.L.peak = -20, -4         # 15 of 30 segments; the peak at 27
v.R.level = v.R.peak = vu.SILENT_DB
l1, l2 = v.lines()
check(len(l1) == len(l2) == 16 and l1[0] == "L" and l2[0] == "R", "deck: two lines, L and R")
check(l1[1:8] == chr(1) * 7 and l1[8] == chr(0), "deck: 15 segments = 7 full cells and a half")
check(l1[14] == chr(3), "deck: the peak in the hot zone, a lone, taller segment")
check(set(l2[1:]) <= {" ", chr(vu.DECK_TICK)} and chr(vu.DECK_TICK) in l2, "deck: silent channel, only the marks")
v.L.clip = True
check(v.lines()[0][15] == chr(4), "deck: the clip lights the whole last cell")

# --- Vu: printed scale ---------------------------------------------------------
v = vu.Vu()
v.configure(cfg(auto=True, layout="scale"))
check(v.glyphs is vu.SCALE_GLYPHS, "scale: the L/R pair glyphs")
bar, ruler = v.lines()
check(ruler == "20      10 6 3 0", "scale: the 20 dB ruler (%r)" % ruler)
check(bar == " " * 16, "scale: no sound, the top line empty")
v.configure(cfg(layout="scale"))      # manual, 40 dB: floor -40, top 0
v.L.level, v.L.peak = -20, -5         # L: 16 of 32 segments; the peak at 28 (cell 13, right)
v.R.level, v.R.peak = -30, -30        # R: 8 segments
bar, ruler = v.lines()
check(bar[:4] == chr(3 * 2 + 2 - 1) * 4, "scale: L and R full in the first 4 cells")
check(bar[4:8] == chr(3 * 2 - 1) * 4, "scale: then only L")
check(bar[13] == chr(3 * 2 - 1) and bar[8:13] == " " * 5, "scale: L's peak alone, in cell 13")
check(ruler.endswith(" 0") and "30" in ruler, "manual 40 dB scale: the ruler down to 30 below the top (%r)" % ruler)
v.R.clip = True
check(v.lines()[1][15] == vu.BLOCK, "scale: on clip, the 0 becomes a full block")

# --- Vu: KX-393 ------------------------------------------------------------------
v = vu.Vu()
v.configure(cfg(layout="kx393"))      # manual: top 0, so the deck's 0 sits at -10 dBFS
check(v.glyphs is vu.KX_GLYPHS, "KX-393: the deck glyphs")
check(len(vu.KX_DB) == len(vu.KX_RULER) == 16, "KX-393: 16 segments and the ruler with 16 places")
check(all(vu.KX_RULER[i] != " " for i in (0, 3, 6, 9, 11, 13, 15)),
      "KX-393: each ruler number starts under its segment")
bar, ruler = v.lines()
check(bar == " " * 16 and ruler == vu.KX_RULER, "KX-393: no sound, only the ruler")
v.L.level, v.L.peak = -10, -4         # L up to the deck's 0 (12 segments); the peak at +6
v.R.level = v.R.peak = -19            # R up to the deck's -10 (7 segments)
bar, _ = v.lines()
check(bar[:7] == chr(2) * 7, "KX-393: L and R together in the first 7")
check(bar[7:12] == chr(0) * 5, "KX-393: then only L, up to 0")
check(bar[12:14] == "  " and bar[14] == chr(3) and bar[15] == " ", "KX-393: L's peak alone at +6, tall")
v.R.clip = True
check(v.lines()[0][15] == chr(4), "KX-393: R's clip lights the last segment, tall")
g = vu.KX_GLYPHS
check(g[0:8] == bytes([0, 0x1E, 0x1E, 0, 0, 0, 0, 0]) and g[8:16] == bytes([0, 0, 0, 0, 0, 0x1E, 0x1E, 0]),
      "KX-393: L on top, R below, with a one-row gap")
check(g[40:48] == bytes([0x1E] * 3 + [0, 0] + [0x1E] * 3), "KX-393: the hot ones are taller")

# --- Vu: automatic scale ---------------------------------------------------
v = vu.Vu()
v.configure(cfg(auto=True, floor=-45, top=-20))
check((v.floor, v.top) == (-60, -40), "automatic: starts low and ignores fixed floor and top")
ticks = v._ticks
v.poll(0)
v.sock.queue.append(frame(-11, -14))
v.poll(46)
check(abs(v.top - (-6)) < 1e-6 and abs(v.floor - (-26)) < 1e-6, "a frame at -11 dB takes the top to -6 at once")
check(v._ticks == ticks and v._px(-11) < 75, "the marks don't change and the bar doesn't fill")
t = 46
for _ in range(22):                    # 1 s of frames at -30 dB
    t += 46
    v.sock.queue.append(frame(-30, -30))
    v.poll(t)
check(-7.2 < v.top < -6.8, "with quieter music, the top drops 1 dB/s (%.2f)" % v.top)
v.sock.queue.append(frame(-50, -50, music=False))
v.poll(t + 46)
check(-7.2 < v.top < -6.8, "without music, the top holds still")
v.sock.queue.append(frame(-90, -90))
for _ in range(300):                   # 60 s (each frame counts for at most 200 ms)
    t += 1000
    v.sock.queue.append(frame(-90, -90))
    v.poll(t)
check(v.top == -40, "the top doesn't drop below -40 dB")
v.sock.queue.append(frame(5, 5))
v.poll(t + 46)
check(v.top == 0, "nor rise above 0 dB")
check(v.status(t + 46)["top"] == 0 and v.status(t + 46)["auto"], "the status shows the current scale")

# --- Vu: request, frames, music -----------------------------------------------
v = vu.Vu()
v.configure(cfg())
check(not v.poll(0) and v.sock.sent == [(b"SUB1", ("192.168.178.105", 7091))], "asks right when turned on")
v.poll(1000)
check(len(v.sock.sent) == 1, "doesn't repeat the request before 2 s")
v.poll(2000)
check(len(v.sock.sent) == 2, "repeats the request every 2 s")
v.sock.queue += [frame(-12, -14), b"lixo", frame(-11, -13)]
check(v.poll(2046) and v.frames == 2, "reads the queued frames and ignores the garbage")
check(v.active(2046), "with music and frames: VU active")
check(not v.active(3100), "no frames for 1 s: back to the amp's screen")
v.sock.queue.append(frame(-12, -14, music=False))
v.poll(3200)
check(not v.active(3200), "no music: the amp's screen")
sock = v.sock
v.configure(cfg(on=False))
check(sock.closed and not v.poll(4000) and not v.active(4000), "off: closes and asks no more")
v.configure(cfg(relay="192.168.178.99"))
v.poll(5000)
check(v.sock.sent[0][1] == ("192.168.178.99", 7091), "board change: asks the new one")

print("\nall good" if not fails else "\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
