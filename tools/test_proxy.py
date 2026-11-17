#!/usr/bin/env python3
"""Simulates firmware/proxy.py on the computer with the amp's .lac captures.

1. Responder (busy.py): checks in the captures the PIO program's assumption that RW
   already holds the right value on E's rising edge and doesn't change until the falling edge.
2. Proxy: runs proxy.py's listen() loop with a fake sniffer, clock and display, fed with
   the words from the captures, and checks that the amp's display shows each of the
   controller's screens already with the custom names (names.rewrite).

    python3 tools/test_proxy.py
"""

import asyncio
import glob
import os
import struct
import sys
import time as real_time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))

import hd44780_decode as hd   # noqa: E402
from test_sniffer import SKIP, screens_from_words, words_from_lac   # noqa: E402

NAMES = {"inputs": {"TUNER": "Rega Planar 2", "TAPE/AUX": "Yamaha KX-393", "CD": "Yamaha CD-S300",
                    "DAB": "AirPlay/BT - DAC"},
         "boot": ["", ""], "about": ["Oceano Amplifier", "SP103"]}


# --- 1. the Responder's assumption ----------------------------------------------

def check_rw(path):
    freq, pre, _, by_number, by_name = hd.load_lac(path)
    sig = hd.pick_signals(by_number, by_name)
    if "RW" not in sig:
        return None
    e, rw = sig["E"], sig["RW"]
    reads = bad = 0
    rise_rw = None
    for i in range(1, len(e)):
        if e[i] and not e[i - 1]:
            rise_rw = rw[i]
        elif e[i - 1] and not e[i] and rise_rw is not None:
            if rw[i - 1]:
                reads += 1
            if rw[i - 1] != rise_rw:
                bad += 1
    return reads, bad


# --- 2. proxy.py ------------------------------------------------------------

class Clock:
    us = 0


def fake_time():
    t = types.ModuleType("time")
    for k in dir(real_time):
        if not k.startswith("__"):
            setattr(t, k, getattr(real_time, k))
    t.ticks_us = lambda: Clock.us
    t.ticks_ms = lambda: Clock.us // 1000
    t.ticks_diff = lambda a, b: a - b
    t.ticks_add = lambda a, b: a + b
    t.sleep_us = t.sleep_ms = lambda n: None
    return t


class FakeLcd:
    """The amp's display, seen from outside: what the proxy told it to show."""
    def __init__(self, *a, **k):
        self.lines, self.cgram, self.on, self.resyncs = [" " * 16, " " * 16], bytearray(64), True, 0

    def reset(self):
        self.lines = [" " * 16, " " * 16]

    def resync(self):
        self.resyncs += 1

    def display(self, on):
        self.on = on

    def define_char(self, code, rows):
        self.cgram[8 * code:8 * code + 8] = bytes(rows)

    def write_line(self, row, text, old=None):
        assert len(text) == 16, text
        assert old is None or old == self.lines[row], (old, self.lines[row])   # the proxy knows what is there
        self.lines[row] = text


class FakeSniffer:
    words = []                          # (µs, word)

    def read(self):
        while self.words and self.words[0][0] <= Clock.us:
            yield self.words.pop(0)[1]


class QuietSource:
    """info.py's UDP socket when the test doesn't use the screens: no packet ever arrives."""
    def __init__(self, *a):
        pass

    def setblocking(self, flag):
        pass

    def sendto(self, data, addr):
        pass

    def recv(self, n):
        raise OSError(11)

    def close(self):
        pass


def load_proxy():
    stubs = {"time": fake_time(), "sniffer": types.SimpleNamespace(Sniffer=FakeSniffer),
             "busy": types.SimpleNamespace(Responder=lambda: None),
             "ir": types.SimpleNamespace(Remote=lambda: types.SimpleNamespace(handle=None)),
             "panel": types.SimpleNamespace(Panel=lambda: None),
             "lcd1602": types.SimpleNamespace(Lcd1602=FakeLcd),
             "ota": types.SimpleNamespace(in_trial=lambda: False, handle=None),
             "web": types.SimpleNamespace(Publisher=None),
             "wifi": types.SimpleNamespace(Wifi=lambda **kw: None)}
    saved = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    run, asyncio.run = asyncio.run, lambda coro: coro.close()   # doesn't run main()
    try:
        import names
        names.load = lambda: names.validate(NAMES)
        names.save = lambda cfg: None
        sys.modules.pop("proxy", None)
        import proxy
        # The Pico always asks for the screen packets: here the source stays silent (nothing goes to the network).
        proxy.info_feed.socket = types.SimpleNamespace(socket=QuietSource, AF_INET=2, SOCK_DGRAM=2)
    finally:
        asyncio.run = run
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k)
            else:
                sys.modules[k] = v
    return proxy


@types.coroutine
def _tick(ms):
    yield ms


def run_capture(proxy, words):
    """Runs the proxy's listen() over the words; returns the screens the display showed."""
    import names
    proxy.asyncio = types.SimpleNamespace(sleep_ms=_tick)
    proxy.powers = []                   # the "power" at each state change
    proxy.pub = types.SimpleNamespace(changed=lambda: proxy.powers.append(proxy.state.power))
    t0 = words[0][0] if words else 0
    FakeSniffer.words = [(int(t - t0) + 1000, w) for t, w in words]
    Clock.us = 0
    end = (FakeSniffer.words[-1][0] if FakeSniffer.words else 0) + 50_000
    shown, loop = [], proxy.listen()
    while Clock.us < end:
        ms = loop.send(None)
        Clock.us += ms * 1000
        cur = tuple(proxy.lcd.lines)
        if not shown or shown[-1] != cur:
            shown.append(cur)
    return shown[1:] if shown and shown[0] == (" " * 16,) * 2 else shown


class FakeRelay:
    """vu.py's UDP socket: the relay delivers a frame every 46 ms, from start to stop (ms)."""
    start, stop, music = 0, 0, True

    def __init__(self, *a):
        self.next = FakeRelay.start

    def setblocking(self, flag):
        pass

    def sendto(self, data, addr):
        pass

    def recv(self, n):
        now = Clock.us // 1000
        if self.next > now or self.next >= FakeRelay.stop:
            raise OSError(11)
        self.next += 46
        return struct.pack("<2sBBff", b"VU", 1, 3 if FakeRelay.music else 2, 0.1, 0.05)

    def close(self):
        pass


def run_vu(proxy, words, end_ms):
    """Runs listen() with the VU on; returns [(ms, "vu" or the amp's screen)] at each change."""
    proxy.asyncio = types.SimpleNamespace(sleep_ms=_tick)
    proxy.pub = types.SimpleNamespace(changed=lambda: None)
    proxy.vu_meter.socket = types.SimpleNamespace(socket=FakeRelay, AF_INET=2, SOCK_DGRAM=2)
    proxy.vu.configure({"on": True, "auto": False, "floor": -40, "top": 0, "layout": "bars",
                        "relay": "192.168.178.105"})
    t0 = words[0][0]
    FakeSniffer.words = [(int(t - t0) + 1_000_000, w) for t, w in words]   # the amp's screen at 1 s
    Clock.us = 0
    changes, loop = [], proxy.listen()
    while Clock.us < end_ms * 1000:
        ms = loop.send(None)
        Clock.us += ms * 1000
        lines = proxy.lcd.lines
        kind = "vu" if lines[0][0] == "L" and lines[1][0] == "R" and proxy.own == "vu" else tuple(lines)
        if not changes or changes[-1][1] != kind:
            changes.append((Clock.us // 1000, kind))
    return changes


def check_vu(path):
    """VU on the air; the amp's screen arrives at 1 s and stays 3 s; the frames stop at 6 s."""
    fails = 0
    proxy = load_proxy()
    FakeRelay.start, FakeRelay.stop, FakeRelay.music = 0, 6000, True
    changes = run_vu(proxy, words_from_lac(path), 8000)
    kinds = [k if k == "vu" else "amp" for _, k in changes if k != (" " * 16,) * 2]
    at = {"vu": [], "amp": []}
    for t, k in changes:
        if k != (" " * 16,) * 2:
            at[k if k == "vu" else "amp"].append(t)
    amp = next((k for _, k in changes if k not in ("vu", (" " * 16,) * 2)), None)

    def ok(cond, what):
        nonlocal fails
        fails += not cond
        print("%-5s %s" % ("ok" if cond else "FAIL", what))

    ok(kinds[:4] == ["vu", "amp", "vu", "amp"], "VU, amp screen, VU, amp screen: %s" % kinds)
    ok(amp == ("Volume -28.75 dB", "Rega Planar 2   "), "the amp's screen already with the name: %r" % (amp,))
    if len(changes) >= 4:
        t_amp, t_vu, t_end = at["amp"][0], at["vu"][1], at["amp"][1]
        ok(1000 <= t_amp <= 1020, "the amp's screen comes in when the controller draws (%d ms)" % t_amp)
        ok(3000 <= t_vu - t_amp <= 3060, "and stays 3 s (%d ms)" % (t_vu - t_amp))
        ok(6900 <= t_end <= 7100, "no frames for 1 s, the amp's screen comes back (%d ms)" % t_end)
    ok(bytes(proxy.lcd.cgram) == bytes(proxy.bus.lcd.cgram), "the controller's glyphs come back")

    proxy = load_proxy()
    FakeRelay.start, FakeRelay.stop, FakeRelay.music = 0, 6000, False
    changes = run_vu(proxy, words_from_lac(path), 3000)
    ok(all(k != "vu" for _, k in changes), "without music, the VU doesn't show")
    return fails


class FakeSource:
    """info.py's UDP socket: the source sends an "NP" packet every 5 s, playing Time (A4)
    from 2:41 at instant 0, like sp103-vu-relay (the times hold at send time)."""
    def __init__(self, *a):
        self.next = 0
        self.sent = []

    def setblocking(self, flag):
        pass

    def sendto(self, data, addr):
        self.sent.append(data)

    def recv(self, n):
        now = Clock.us // 1000
        if self.next > now:
            raise OSError(11)
        self.next += 5000
        s = now // 1000
        fields = ["Pink Floyd", "Time", "A4", str(161 + s), "421", "A", "4", "5", str(544 - s), "312", "62"]
        return b"NP\x01\x01" + "\x1f".join(fields).encode()

    def close(self):
        pass


def run_info(proxy, words, end_ms, info_cfg):
    """Runs listen() with the screens on (and the VU saved as on); returns the screens at each change."""
    import names
    proxy.asyncio = types.SimpleNamespace(sleep_ms=_tick)
    proxy.pub = types.SimpleNamespace(changed=lambda: None)
    proxy.vu_meter.socket = types.SimpleNamespace(socket=FakeRelay, AF_INET=2, SOCK_DGRAM=2)
    proxy.info_feed.socket = types.SimpleNamespace(socket=FakeSource, AF_INET=2, SOCK_DGRAM=2)
    FakeRelay.start, FakeRelay.stop, FakeRelay.music = 0, end_ms, True
    cfg = names.validate(dict(NAMES, vu={"on": True, "relay": "192.168.178.99"}, info=info_cfg))
    proxy.configure_feeds(cfg)
    proxy.amp_until = 0
    t0 = words[0][0]
    FakeSniffer.words = [(int(t - t0) + 1_000_000, w) for t, w in words]   # the amp's screen at 1 s
    Clock.us = 0
    changes, loop = [], proxy.listen()
    while Clock.us < end_ms * 1000:
        ms = loop.send(None)
        Clock.us += ms * 1000
        kind = proxy.own or tuple(proxy.lcd.lines)
        if not changes or changes[-1][1] != kind:
            changes.append((Clock.us // 1000, kind, tuple(proxy.lcd.lines)))
    return changes


def check_info(path):
    """Info screens: the stylus in fixed and temporary mode, with the amp's screen in between."""
    fails = 0

    def ok(cond, what):
        nonlocal fails
        fails += not cond
        print("%-5s %s" % ("ok" if cond else "FAIL", what))

    proxy = load_proxy()
    changes = run_info(proxy, words_from_lac(path), 6000, {"on": True, "mode": "fixed"})
    kinds = [k if isinstance(k, str) else "amp" for _, k, _ in changes if k != (" " * 16,) * 2]
    ok(kinds == ["amp", "stylus"], "fixed, on the turntable (TUNER): the amp's screen, then the stylus: %s" % kinds)
    ok(not proxy.vu.on, "fixed: the VU doesn't even ask for frames")
    first = next(l for _, k, l in changes if k == "stylus")
    ok(first[0] == "Stylus     312 h" and first[1].endswith(" 62%"), "the stylus screen: %r" % (first,))
    ok(bytes(proxy.lcd.cgram[:64]) == proxy.screens_mod.GLYPHS, "the screens use the VU's bar glyphs")

    proxy = load_proxy()
    changes = run_info(proxy, words_from_lac(path), 30000, {"on": True, "mode": "temp", "secs": 5})
    kinds = []
    for _, k, _ in changes:
        k = k if isinstance(k, str) else "amp"
        if k != "amp" or not kinds or kinds[-1] != "amp":
            kinds.append(k)
    ok(kinds == ["vu", "amp", "stylus", "vu"], "temporary: the amp's screen shows the input (TUNER), the stylus, "
       "then the VU: %s" % kinds)
    # The last occurrence of each screen is the relevant one: there is a VU before the amp's
    # screen and another after the stylus. Plain iteration lets the last one win.
    at = {k: t for t, k, _ in changes if isinstance(k, str)}
    ok(4990 <= at["vu"] - at["stylus"] <= 5110, "the stylus stays 5 s: %d ms" % (at["vu"] - at["stylus"]))

    proxy = load_proxy()
    run_info(proxy, words_from_lac(path), 1500, {"on": True, "mode": "fixed"})
    proxy.state.power = "standby"
    loop = proxy.listen()
    for _ in range(3000):
        Clock.us += loop.send(None) * 1000
    ok(proxy.own != "clock", "standby: no clock any more (removed 2026-11-16): %r" % (proxy.own,))
    return fails


class StreamSource(QuietSource):
    """info.py's UDP socket: the source sends an "NP" packet every 5 s, with the streaming from
    StreamSource.stream ("bluetooth", "airplay" or "") and nothing about the record."""
    stream = ""

    def __init__(self, *a):
        self.next = 0

    def recv(self, n):
        now = Clock.us // 1000
        if self.next > now:
            raise OSError(11)
        self.next += 5000
        fields = [""] * 11 + [StreamSource.stream, "SBC", "44100", "16", "328"]
        return b"NP\x01\x00" + "\x1f".join(fields).encode()


def check_stream(path):
    """DAB input (09-dab.lac, named "Streaming"): the streaming's name in its place."""
    import names
    fails = 0

    def ok(cond, what):
        nonlocal fails
        fails += not cond
        print("%-5s %s" % ("ok" if cond else "FAIL", what))

    words = words_from_lac(path)
    for stream, want in (("bluetooth", "\x07 Bluetooth     "), ("airplay", "AirPlay         "),
                         ("", "Streaming       ")):
        proxy = load_proxy()
        proxy.texts = names.validate({"inputs": {"DAB": "Streaming"}, "vu": {"relay": "192.168.178.99"}})
        proxy.configure_feeds(proxy.texts)
        proxy.info_feed.socket = types.SimpleNamespace(socket=StreamSource, AF_INET=2, SOCK_DGRAM=2)
        StreamSource.stream = stream
        got = run_capture(proxy, words)
        line2 = got[-1][1] if got else None
        ok(line2 == want, "%s: the input line shows %r" % (stream or "no streaming", line2))
        glyph7 = bytes(proxy.lcd.cgram[56:])
        want7 = proxy.screens_mod.BT_GLYPH if stream == "bluetooth" else bytes(proxy.bus.lcd.cgram[56:])
        ok(glyph7 == want7, "  glyph 7: %s" % ("the Bluetooth symbol" if stream == "bluetooth"
                                                 else "the controller's"))
    return fails


def main():
    paths = sorted(glob.glob(os.path.join(HERE, "..", "captures", "*.lac")))
    fails = 0
    print("1. Responder: RW the same on E's rising and falling edges")
    for p in paths:
        r = check_rw(p)
        name = os.path.basename(p)
        if r is None:
            print("--    %-24s no RW" % name)
            continue
        reads, bad = r
        ok = bad == 0 or name in SKIP
        fails += not ok
        print("%-5s %-24s %4d reads, %d changes mid-pulse%s"
              % ("ok" if ok else "FAIL", name, reads, bad, " (loose wires)" if bad and ok else ""))

    print("\n2. Proxy: the display shows each of the controller's screens, with the names")
    import names
    for p in paths:
        name = os.path.basename(p)
        if name in SKIP:
            continue
        proxy = load_proxy()
        words = words_from_lac(p)
        expected, _ = screens_from_words(words)
        want = []
        for l1, l2 in expected:
            s = tuple(names.rewrite(l1, l2, proxy.texts))
            if not want or want[-1] != s:
                want.append(s)
        if want and want[0] == (" " * 16,) * 2:
            want = want[1:]             # blank screen: the display already starts that way
        got = run_capture(proxy, words)
        # busy_high here comes from the captures' real display (busy right after
        # "Clear display"); only in the amp, with the Responder, does it need to stay at 0.
        ok = got == want and (not got or bytes(proxy.lcd.cgram) == bytes(proxy.bus.lcd.cgram))
        # No capture has standby: the blank screen at power-on must not become "standby".
        ok = ok and "standby" not in proxy.powers
        fails += not ok
        last = " | ".join(got[-1]) if got else "(nothing)"
        print("%-5s %-24s %3d screens, busy_high=%d, power=%s  ->  %s"
              % ("ok" if ok else "FAIL", name, len(got), proxy.busy_high, proxy.state.power, last))
        if not ok and got != want:
            for i, (g, w) in enumerate(zip(got + [None] * len(want), want + [None] * len(got))):
                if g != w:
                    print("      screen %d: showed %r, expected %r" % (i, g, w))
                    break

    print("\n3. VU: alternates with the amp's screen (05-tuner.lac)")
    fails += check_vu(os.path.join(HERE, "..", "captures", "05-tuner.lac"))
    print("\n4. Info screens (05-tuner.lac)")
    fails += check_info(os.path.join(HERE, "..", "captures", "05-tuner.lac"))
    print("\n5. Streaming on the DAB input (09-dab.lac)")
    fails += check_stream(os.path.join(HERE, "..", "captures", "09-dab.lac"))
    print("\nall good" if not fails else "\n%d failure(s)" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
