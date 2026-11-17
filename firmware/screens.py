"""What appears on the display, and the text of the info screens.

proxy.py calls pick() when the amp screen does not have the turn (3 s after each
controller redraw). There are two screens, each on its own input:

- "stylus": stylus hours and wear, only on the turntable inputs ("turntable":
  PHONO, TUNER...).
- "quality": the Bluetooth quality (codec, sample rate, bits, bitrate), only on the
  streaming input (amp_state.STREAMING_INPUT) with Bluetooth playing.

In order:

1. Standby: the amp's own screen (blank). (The standby clock was removed on 2026-11-16: not useful.)
2. Fixed mode: the selected screen for the current input, all the time. The VU stays out.
3. Temporary mode: the selected screen comes in for "secs". The stylus, when the amp
   switches to a turntable input and when the record starts playing; the quality, when
   Bluetooth starts or the quality changes. Then the VU, if on; otherwise, the amp screen.
4. No data: the VU (which only shows with music) or the amp screen.

The streaming name on the amp screen ("AirPlay", "Bluetooth") is stream_label(), which
proxy.py passes to names.rewrite().

The texts are in English, like the amp's. The bars use the VU characters (vu.GLYPHS);
character 7 (the VU clip, which the screens do not use) becomes the Bluetooth symbol.
"""

import time

import vu as vu_meter
from amp_state import STREAMING_INPUT

KINDS = ("stylus", "quality")
STYLUS_WARN = 90                # % wear: "Replace stylus"
BT = 7                          # the code of the Bluetooth symbol (ᛒ) among our custom characters
BT_GLYPH = bytes((0x04, 0x06, 0x15, 0x0E, 0x0E, 0x15, 0x06, 0x04))
GLYPHS = vu_meter.GLYPHS[:8 * BT] + BT_GLYPH
STREAM_NAMES = {"airplay": "AirPlay", "bluetooth": chr(BT) + " Bluetooth"}


def lr(left, right):
    """Text on the left and on the right of a 16-character line."""
    gap = 16 - len(left) - len(right)
    return (left + " " * max(1, gap) + right)[:16]


def khz(rate):
    """44100 -> "44.1kHz", 48000 -> "48kHz"."""
    if rate % 1000 == 0:
        return "%dkHz" % (rate // 1000)
    return "%d.%dkHz" % (rate // 1000, rate % 1000 // 100)


def with_bt_glyph(cgram):
    """The controller's characters with the Bluetooth symbol at 7 (for the amp screen)."""
    return bytes(cgram[:8 * BT]) + BT_GLYPH


def bar(fraction, cells):
    """A bar made of the VU characters: 5 pixel columns per cell."""
    n = int(max(0, min(1, fraction)) * cells * 5 + 0.5)
    out = []
    for c in range(cells):
        filled = n - 5 * c
        out.append(chr(vu_meter.FULL) if filled >= 5 else chr(filled - 1) if filled > 0 else " ")
    return "".join(out)


class Screens:
    def __init__(self, info):
        self.info = info
        self.cfg = {"on": False, "mode": "temp", "show": list(KINDS), "secs": 8, "turntable": []}
        self.seen_stream = 0
        self.quality_at = None          # when the "quality" screen came in (temporary mode)
        self.stylus_at = None           # when the "stylus" screen came in (temporary mode)
        self.was_playing = False
        self.seen_input = None          # the input _pick() last saw, with data
        self.key = None
        self.since = 0
        self.input = None               # the amp's current input ("TUNER"), from amp_state
        self.error = None

    def configure(self, cfg):
        """cfg = names.json "info" (names.py)."""
        self.cfg = cfg
        self.seen_stream = self.info.stream_seq
        self.quality_at = self.stylus_at = None
        self.was_playing = self.info.playing
        self.error = None

    def vu_allowed(self):
        """In fixed mode the VU stays out: the Pico does not even request the frames."""
        return not (self.cfg["on"] and self.cfg["mode"] == "fixed")

    def _has(self, kind):
        d = self.info.data
        if kind not in self.cfg["show"]:
            return False
        if kind == "stylus":
            return d["stylus_hours"] is not None and self.input in self.cfg["turntable"]
        if kind == "quality":
            return d["stream"] == "bluetooth" and self.input == STREAMING_INPUT \
                and (d["codec"] is not None or d["sample_rate"] is not None)
        return False

    def stream_label(self, now):
        """The name of the stream playing ("AirPlay", "ᛒ Bluetooth"), for the input line on
        the amp screen, or None. Applies with or without the screens on."""
        if not self.info.fresh(now):
            return None
        return STREAM_NAMES.get(self.info.data["stream"])

    def pick(self, now, standby, vu_active, amp_input=None):
        """The current screen: "vu", one of the info screens, or None (the amp screen)."""
        self.input = amp_input
        key = self._pick(now, standby, vu_active)
        if key != self.key:
            self.key, self.since = key, now
        return key

    def _shown(self, at, now):
        return at is not None and time.ticks_diff(now, at) < self.cfg["secs"] * 1000

    def _pick(self, now, standby, vu_active):
        cfg, info = self.cfg, self.info
        if standby:
            return None
        if not cfg["on"] or not info.fresh(now):
            return "vu" if vu_active else None
        quality, stylus = self._has("quality"), self._has("stylus")
        if info.stream_seq != self.seen_stream:
            self.seen_stream = info.stream_seq
            self.quality_at = now if quality else None
        # Only with data: an input change before the first packet still counts.
        entered = self.input != self.seen_input
        started = info.playing and not self.was_playing
        self.seen_input, self.was_playing = self.input, info.playing
        if stylus and (entered or started):
            self.stylus_at = now
        if cfg["mode"] == "fixed":
            return "quality" if quality else "stylus" if stylus else None
        if quality and self._shown(self.quality_at, now):
            return "quality"
        if stylus and self._shown(self.stylus_at, now):
            return "stylus"
        return "vu" if vu_active else None

    def lines(self, key, now):
        """The two lines (16 characters each) of an info screen."""
        d = self.info.data
        if key == "stylus":
            wear = d["stylus_wear"]
            l1 = "Replace stylus" if wear is not None and wear >= STYLUS_WARN \
                else lr("Stylus", "%d h" % d["stylus_hours"])
            l2 = (bar(wear / 100, 12) + "%4s" % ("%d%%" % wear)) if wear is not None else ""   # no rjust in MicroPython
        elif key == "quality":
            l1 = lr(STREAM_NAMES["bluetooth"], d["codec"] or "")
            fmt = [khz(d["sample_rate"])] if d["sample_rate"] else []
            if d["bit_depth"]:
                fmt.append("%db" % d["bit_depth"])
            l2 = lr(" ".join(fmt), "%dk" % d["bitrate"] if d["bitrate"] else "")
        else:
            l1 = l2 = ""
        return (l1 + " " * 16)[:16], (l2 + " " * 16)[:16]

    def status(self, now):
        return {"on": self.cfg["on"], "mode": self.cfg["mode"], "showing": self.key, "error": self.error}
