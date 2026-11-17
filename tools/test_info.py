#!/usr/bin/env python3
"""Tests the info screens on the computer: firmware/info.py (the "NP" packet),
firmware/screens.py (which one shows and its text) and the settings (names.py "info").

    python3 tools/test_info.py
"""

import os
import sys
import time as real_time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))

fake_time = types.ModuleType("time")
for k in dir(real_time):
    if not k.startswith("__"):
        setattr(fake_time, k, getattr(real_time, k))
fake_time.ticks_add = lambda a, b: a + b
fake_time.ticks_diff = lambda a, b: a - b
sys.modules["time"] = fake_time

import info      # noqa: E402
import names     # noqa: E402
import screens   # noqa: E402

sys.modules["time"] = real_time
fails = 0


def check(ok, what):
    global fails
    fails += not ok
    print("%-5s %s" % ("ok" if ok else "FAIL", what))


def packet(fields, playing=True):
    flags = 1 if playing else 0
    return b"NP\x01" + bytes([flags]) + "\x1f".join(fields).encode()


def time_a4(elapsed, side_left, artist="Pink Floyd", title="Time", pos="A4", track="4"):
    return [artist, title, pos, str(elapsed), "421", "A", track, "5", str(side_left), "312", "62"]


def cfg(**kw):
    return names.validate({"info": dict({"on": True}, **kw)})["info"]


# --- info.py: the packet ---------------------------------------------------------
i = info.Info()
i.on = True
i.feed(packet(time_a4(161, 544)), 1000)
check(i.data["artist"] == "Pink Floyd" and i.data["stylus_hours"] == 312 and i.data["stylus_wear"] == 62,
      "reads the packet's fields")
check(i.playing and i.stream_seq == 0, "playing; no streaming")
i.feed(packet(time_a4(161, 544), playing=False, ), 2000)
check(not i.playing, "stopped")
i.feed(packet(["x"]), 3000)
check(i.data["stylus_hours"] is None, "fields missing at the end: None")
i.feed(packet(time_a4(10, 20)[:9] + ["abc", "62"]), 3500)
check(i.data["stylus_hours"] is None, "broken number: None")
check(i.fresh(3500 + info.STALE_MS - 1) and not i.fresh(3500 + info.STALE_MS), "no packet for 15 s: no longer valid")
check(set(i.status(3500)) == {"on", "packets", "last_packet_ms", "playing", "stream"}, "the status for the app")


class FakeSock:
    def __init__(self, *a):
        self.sent, self.queue = [], []

    def setblocking(self, f):
        pass

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def recv(self, n):
        if not self.queue:
            raise OSError(11)
        return self.queue.pop(0)

    def close(self):
        pass


info.socket = types.SimpleNamespace(socket=FakeSock, AF_INET=2, SOCK_DGRAM=2)
i = info.Info()
i.configure(True, "192.168.178.99")
check(not i.poll(0) and i.sock.sent == [(b"SUB2\x02", ("192.168.178.99", 7091))], "asks the source for the screens only")
i.sock.queue += [b"lixo", "NP\x01\x01Björk".encode("utf-8"), packet(time_a4(1, 2))]
check(i.poll(100) and i.packets == 1, "ignores garbage and non-ASCII packets")
i.configure(False, "192.168.178.99")
check(i.sock is None and not i.poll(200) and not i.fresh(200), "off: closes and doesn't ask")

# --- screens.py: texts ---------------------------------------------------------
check(screens.lr("Side A", "track 4/5") == "Side A track 4/5", "left and right in 16")
check(screens.bar(0.62, 12) == chr(4) * 7 + chr(1) + " " * 4, "62 % bar in 12 cells")
check(screens.bar(0, 4) == "    " and screens.bar(1.5, 2) == chr(4) * 2, "empty and full bar")


def make(**kw):
    i = info.Info()
    i.on = True
    s = screens.Screens(i)
    s.configure(cfg(**kw))
    return i, s


i, s = make(mode="fixed")
check(not s.vu_allowed(), "fixed: the VU doesn't come in")
i.feed(packet(time_a4(161, 544)), 0)
check(s.pick(0, False, True, "PHONO") == "stylus", "fixed: the stylus on the turntable")
check(s.pick(10000, False, True, "PHONO") == "stylus", "  all the time")
check(s.pick(10000, False, True, "CD") is None, "fixed: on another input, the amp's screen")
check(s.lines("stylus", 0) == ("Stylus     312 h", chr(4) * 7 + chr(1) + "     62%"), "the stylus screen")
i.feed(packet(time_a4(161, 544)[:9] + ["320", "95"]), 100)
check(s.lines("stylus", 100)[0] == "Replace stylus  ", "worn stylus: the warning")
i.feed(packet(time_a4(161, 544)[:9] + ["", ""]), 200)
check(s.pick(200, False, True, "PHONO") is None, "without the stylus data: the amp's screen")
check(s.pick(200, True, False) is None, "standby: the amp's own screen (no clock since 2026-11-16)")
s.configure(cfg(mode="fixed"))
check(s.pick(400 + info.STALE_MS, False, True) == "vu", "no data: the VU, if there is music")

i, s = make(mode="temp", secs=8, turntable=["TUNER"])
check(s.vu_allowed(), "temporary: the VU may come in")
playing_a4 = packet(time_a4(0, 900))
stopped = packet(time_a4(0, 900), playing=False)
i.feed(stopped, 0)
check(s.pick(0, False, True, "CD") == "vu", "CD: no stylus")
check(s.pick(1000, False, True, "TUNER") == "stylus", "switched to the turntable: the stylus")
check(s.pick(8999, False, True, "TUNER") == "stylus" and s.pick(9000, False, True, "TUNER") == "vu",
      "  for 'secs' (8 s), then the VU")
check(s.pick(20000, False, False, "TUNER") is None, "  without the VU, the amp's screen")
i.feed(playing_a4, 30000)
check(s.pick(30000, False, True, "TUNER") == "stylus", "the record started playing: the stylus again")
i.feed(playing_a4, 35000)
check(s.pick(40000, False, True, "TUNER") == "vu", "the same record playing: doesn't come back")
i.feed(packet(time_a4(0, 900, title="Money", pos="B1", track="1")), 45000)
check(s.pick(45000, False, True, "TUNER") == "vu", "new track: doesn't come back")

i, s = make(mode="temp", turntable=["PHONO"])
check(s.pick(0, False, True, "PHONO") == "vu", "no data yet: the VU")
i.feed(stopped, 500)
check(s.pick(500, False, True, "PHONO") == "stylus", "the input was already the turntable before the first packet: counts")
i, s = make(mode="temp", show=["quality"], turntable=["PHONO"])
i.feed(stopped, 0)
check(s.pick(0, False, True, "PHONO") == "vu", "stylus unchecked: doesn't show")
check(cfg(turntable=["TUNER", "PHONO"])["turntable"] == ["PHONO", "TUNER"], "the turntable inputs in the amp's order")
s.configure(cfg(on=False))
check(s.pick(80000, False, True) == "vu" and s.pick(80000, True, False) is None, "screens off: as before")

# --- names.py: the settings ------------------------------------------------------
d = names.validate({})["info"]
check(d == {"on": False, "mode": "temp", "show": ["stylus", "quality"], "secs": 8, "source": "",
            "turntable": ["PHONO", "TUNER"]},
      "default: off")
old = cfg(mode="fixed", fixed="pos", show=["track", "pos", "side", "stylus"], alert=False, scroll=True)
check(old["show"] == ["stylus"] and "fixed" not in old and "alert" not in old and "scroll" not in old,
      "old names.json: the removed screens and their options are ignored")
check(names.INFO_KINDS == screens.KINDS, "names.py and screens.py know the same screens")

# --- streaming: the name on the amp's screen and the "quality" screen ---------------------------
EMPTY11 = [""] * 11                     # nothing from groove-identity: no record playing
bt_sbc = packet(EMPTY11 + ["bluetooth", "SBC", "44100", "16", "328"], playing=False)
airplay = packet(EMPTY11 + ["airplay", "", "44100", "16", ""], playing=False)
silent = packet(EMPTY11, playing=False)

i, s = make(mode="temp", secs=8)
i.feed(airplay, 0)
check(s.stream_label(0) == "AirPlay", "AirPlay playing: the name")
check(names.rewrite("Volume -40.00 dB", "DAB" + " " * 13, names.validate({"inputs": {"DAB": "Streaming"}}), "AirPlay")
      == ("Volume -40.00 dB", "AirPlay         "), "on the amp's screen, \"AirPlay\" instead of \"Streaming\"")
check(names.rewrite("Volume -40.00 dB", "DAB" + " " * 13, names.validate({"inputs": {"DAB": "Streaming"}}), None)
      == ("Volume -40.00 dB", "Streaming       "), "no streaming: the chosen name")
check(names.rewrite("Volume -40.00 dB", "CD" + " " * 14, names.validate({}), "AirPlay")[1] == "CD" + " " * 14,
      "  only on the streaming input (DAB)")
check(s.pick(0, False, False, "DAB") is None, "AirPlay: no quality screen (Bluetooth only)")

i.feed(bt_sbc, 1000)
check(s.stream_label(1000) == chr(screens.BT) + " Bluetooth", "Bluetooth: the symbol and the name")
check(s.pick(1000, False, False, "DAB") == "quality", "Bluetooth started: the quality screen")
check(s.lines("quality", 1000) == (chr(screens.BT) + " Bluetooth  SBC", "44.1kHz 16b 328k"), "the screen: %r"
      % (s.lines("quality", 1000),))
check(s.pick(1000 + 7999, False, False, "DAB") == "quality" and s.pick(1000 + 8000, False, False, "DAB") is None,
      "  stays 'secs' (8 s) and leaves")
i.feed(bt_sbc, 10000)
check(s.pick(10000, False, False, "DAB") is None, "repeated packet: doesn't come back")
i.feed(packet(EMPTY11 + ["bluetooth", "AAC", "48000", "16", "256"], playing=False), 12000)
check(s.pick(12000, False, False, "DAB") == "quality" and s.lines("quality", 12000)[1] == "48kHz 16b   256k",
      "the quality changed: the screen comes back")
check(s.pick(12000, False, False, "PHONO") is None, "another input: no quality screen")
i.feed(silent, 13000)
check(s.stream_label(13000) is None, "streaming stopped: no name")
check(s.stream_label(13000 + info.STALE_MS) is None, "no packets: no name")

i, s = make(mode="fixed")
i.feed(bt_sbc, 0)
check(s.pick(0, False, False, "DAB") == "quality" and s.pick(10000, False, False, "DAB") == "quality",
      "fixed: the quality screen all the time on Bluetooth")
i, s = make(mode="temp", show=["stylus"])
i.feed(bt_sbc, 0)
check(s.pick(0, False, False, "DAB") is None, "temporary without the screen checked: doesn't show")
check(screens.GLYPHS[8 * screens.BT:] == screens.BT_GLYPH and screens.GLYPHS[:8 * screens.BT] ==
      screens.vu_meter.GLYPHS[:8 * screens.BT], "the Bluetooth symbol in glyph 7; the bar's glyphs stay")
check(cfg(show=["quality", "stylus"])["show"] == ["stylus", "quality"], "the checked screens stay in the right order")
check(cfg(source=" 192.168.178.99 ")["source"] == "192.168.178.99", "IP with spaces")
old_clock = cfg(clock=True, utc_offset=5.5, eu_dst=False)
check(not any(k in old_clock for k in ("clock", "utc_offset", "eu_dst")), "the removed clock's keys are accepted and dropped")
check(names.validate({"info": {"on": True}})["vu"]["on"] is False, "the screens don't touch the VU")
for bad in ({"mode": "always"}, {"show": ["stylus", "lyrics"]}, {"show": "stylus"},
            {"secs": 2}, {"secs": 8.5}, {"secs": True},
            {"source": "oceano.local"}, {"on": "yes"}, {"turntable": ["RADIO"]}, {"turntable": "TUNER"}):
    try:
        names.validate({"info": bad})
        check(False, "refuses %r" % bad)
    except ValueError:
        check(True, "refuses %r" % bad)

# udp.py: with poll (MicroPython), recv() is only called with a packet queued.
import udp   # noqa: E402


class FakePoll:
    def register(self, sock, mask):
        self.sock = sock

    def ipoll(self, timeout):
        return iter([(self.sock, 1)] if self.sock.queue else [])


class CountingSock(FakeSock):
    recvs = 0

    def recv(self, n):
        CountingSock.recvs += 1
        return FakeSock.recv(self, n)


real_select = udp.select
udp.select = types.SimpleNamespace(poll=FakePoll, POLLIN=1)
info.socket = types.SimpleNamespace(socket=CountingSock, AF_INET=2, SOCK_DGRAM=2)
i = info.Info()
i.configure(True, "192.168.178.99")
for t in range(0, 1000, 10):
    i.poll(t)
check(CountingSock.recvs == 0 and isinstance(i._poll, FakePoll), "empty queue: doesn't even call recv (no error)")
i.sock.queue.append(packet(time_a4(1, 2)))
check(i.poll(1000) and CountingSock.recvs == 1, "with a packet: reads just that one")
i.configure(False, "192.168.178.99")
check(i._poll is None, "off: drops the poll along with the socket")
udp.select = real_select
check(udp.poller(FakeSock()) is None and udp.ready(None), "socket without poll: falls back to recv with an error, as before")

print("\nall good" if not fails else "\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
