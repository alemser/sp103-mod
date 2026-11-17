"""LCD bus statistics and a timestamped log of the last words read.

    GET  /bus.json     the statistics as JSON
    GET  /bus.csv      the last words, oldest first
                       (?tz=<minutes>: time zone)
    POST /bus/clear    resets the log and the statistics (to start a clean test)

CSV columns: time (wall time, if the Pico has set its clock from the internet), ms (the
Pico's internal clock, in ms), rs, rw, byte (hex), meaning (see hd44780.describe). The CSV
opens in Numbers/Excel and in tools/ler_bus.py, which rebuilds the screens.

Each word's time is when Python READ it, and Python picks up words in batches (every
~1 ms, or longer when Wi-Fi is busy): words in the same batch share the same time, but
the order is always right. For fine timing, use the logic analyser.

Runs the same on MicroPython (Pico) and on the computer's Python (tools/test_buslog.py).
"""

import gc
import time
from array import array

from amp_state import lcd_text
from hd44780 import RS, RW, DATA_SHIFT, describe

try:
    from time import ticks_diff
except ImportError:             # on the computer the clock does not wrap around
    def ticks_diff(a, b):
        return a - b

SIZE = 8192                     # words kept (about 50 screens; 48 KB of RAM)
WARN_BATCH = 3000               # the sniffer holds 4096: a batch near that may have lost words


class BusLog:
    def __init__(self, bus, size=SIZE):
        self.bus = bus                          # the listener's hd44780.Bus (counters)
        self.size = size
        self.words = array("H", bytes(2 * size))
        self.ticks = array("I", bytes(4 * size))
        self.clock = None                       # (seconds since 1970, ticks_ms) from the internet clock set
        self.clear(None)

    def clear(self, now_ms):
        self.n = 0                              # words kept since the start (wraps around the buffer)
        self.since = now_ms
        self.screens = 0
        self.unknown = 0                        # screens the reader (amp_state) did not recognise
        self.last_screen = None
        self.max_gap = 0                        # longest pause between two sniffer reads (ms)
        self.max_batch = 0                      # most words in a single read
        self.last_poll = None
        self.base = (self.bus.writes, self.bus.reads, self.bus.clears)

    def poll(self, now_ms, count):
        """Call on every sniffer read, with the number of words read."""
        if self.last_poll is not None:
            self.max_gap = max(self.max_gap, ticks_diff(now_ms, self.last_poll))
        self.last_poll = now_ms
        self.max_batch = max(self.max_batch, count)

    def add(self, now_ms, word):
        i = self.n % self.size
        self.words[i] = word
        self.ticks[i] = now_ms
        self.n += 1

    def screen(self, now_ms, known):
        self.screens += 1
        self.unknown += not known
        self.last_screen = now_ms

    def set_clock(self, epoch_s, now_ms):
        self.clock = (epoch_s, now_ms)

    def _wall(self, t_ms, tz_min):
        """'2026-10-24 21:15:03.120' (in time zone tz_min), or '' if the clock is not set."""
        if not self.clock:
            return ""
        ms = self.clock[0] * 1000 + ticks_diff(t_ms, self.clock[1]) + tz_min * 60000
        t = time.gmtime(ms // 1000)
        return "%04d-%02d-%02d %02d:%02d:%02d.%03d" % (t[0], t[1], t[2], t[3], t[4], t[5], ms % 1000)

    def stats(self, now_ms):
        writes, reads, clears = (a - b for a, b in zip(
            (self.bus.writes, self.bus.reads, self.bus.clears), self.base))
        kept = min(self.n, self.size)
        oldest = self.ticks[(self.n - kept) % self.size] if kept else None
        return {
            "since_s": ticks_diff(now_ms, self.since) // 1000 if self.since is not None else None,
            "words": self.n, "writes": writes, "reads": reads, "power_ons": clears,
            "screens": self.screens, "unknown_screens": self.unknown,
            "last_screen_s": ticks_diff(now_ms, self.last_screen) // 1000 if self.last_screen else None,
            "max_gap_ms": self.max_gap, "max_batch": self.max_batch,
            "maybe_lost": self.max_batch >= WARN_BATCH,
            "log_words": kept, "log_size": self.size,
            "log_span_s": ticks_diff(now_ms, oldest) // 1000 if kept else 0,
            "clock": self._wall(now_ms, 0) or None,
            "lcd": [lcd_text(line) for line in self.bus.lcd.lines()],
        }

    def csv(self, tz_min=0, chunk=100):
        """The log as CSV, in text chunks (a generator). Goes only up to the last word present
        when the download started. No copy (it would not fit in memory): words arriving between
        one chunk and the next go to the end of the buffer; if so many arrive that they
        overwrite ones not yet sent, those are skipped."""
        size, end = self.size, self.n
        k = max(0, end - size)
        yield "time,ms,rs,rw,byte,meaning\n"
        while k < end:
            k = max(k, self.n - size)
            stop = min(k + chunk, end)
            lines = []
            for j in range(k, stop):
                w, t = self.words[j % size], self.ticks[j % size]
                lines.append('%s,%d,%d,%d,%02X,"%s"\n' % (
                    self._wall(t, tz_min), t, (w & RS) > 0, (w & RW) > 0, (w >> DATA_SHIFT) & 0xFF,
                    describe(w).replace('"', '""')))
            k = stop
            if lines:
                yield "".join(lines)
            gc.collect()                        # small chunks and clean memory: the Pico has little

    async def handle(self, req, writer):
        """Route /bus (see web.Publisher)."""
        from web import reply, reply_json
        now = time.ticks_ms()
        if req.path == "/bus.json":
            await reply_json(writer, self.stats(now))
        elif req.path == "/bus/clear" and req.method == "POST":
            self.clear(now)
            await reply_json(writer, self.stats(now))
        elif req.path == "/bus.csv":
            try:
                tz = int(req.query.get("tz", 0))
            except ValueError:
                tz = 0
            name = "sp103-bus.csv"
            if self.clock:
                name = "sp103-bus-%s.csv" % self._wall(now, tz)[:16].replace(" ", "-").replace(":", "")
            # No Content-Length: the size is only known at the end; the connection closes when done.
            writer.write(("HTTP/1.1 200 OK\r\nContent-Type: text/csv; charset=utf-8\r\n"
                          "Content-Disposition: attachment; filename=\"%s\"\r\n"
                          "Connection: close\r\n\r\n" % name).encode())
            for part in self.csv(tz):
                writer.write(part.encode())
                await writer.drain()            # here the listener keeps running between chunks
        else:
            await reply(writer, "404 Not Found", "text/plain", b"not found\n")
