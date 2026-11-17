#!/usr/bin/env python3
"""
Decoder for the HD44780 bus (16x2 LCD) from a LogicAnalyzer (gusmanb)
capture.

Usage:
    python3 tools/hd44780_decode.py captura.lac
    python3 tools/hd44780_decode.py captura.csv --freq 10000000

What it does:
  1. Finds every FALLING edge of the E signal (that is when the LCD "reads" the byte).
  2. At that instant, reads RS, RW and D0..D7.
       RS=0 -> command     RS=1 -> character
       RW=1 -> read (the controller is reading the LCD, usually the busy flag)
  3. Turns each command into text and keeps a copy of the LCD's memory
     (DDRAM), to show what the screen looks like after each burst of writes.

Expected wiring (analyzer channel -> LCD signal), as in docs/analyzer-wiring.md:
    CH1=E  CH2=RS  CH3=RW  CH4..CH11=D0..D7
If you named the channels in the program (E, RS, RW, D0..D7), the names take priority.
"""

import argparse
import base64
import csv
import json
import sys

# Default wiring: channel number (1 = Channel 1) for each signal.
DEFAULT_MAP = {"E": 1, "RS": 2, "RW": 3,
               "D0": 4, "D1": 5, "D2": 6, "D3": 7,
               "D4": 8, "D5": 9, "D6": 10, "D7": 11}

SIGNALS = list(DEFAULT_MAP)

# Bus silence longer than this (in µs) ends a "burst" of writes.
BURST_GAP_US = 2000


# ---------------------------------------------------------------------------
# Reading the files
# ---------------------------------------------------------------------------

def load_lac(path):
    """.lac file = JSON saved by the LogicAnalyzer (File > Save)."""
    with open(path, encoding="utf-8-sig") as f:
        doc = json.load(f)
    settings = doc["Settings"]
    freq = settings["Frequency"]
    pre = settings.get("PreTriggerSamples", 0)
    # Burst mode: the capture is made of several stretches of PostTriggerSamples samples,
    # each starting at a new trigger. The stretches are stuck one after the other.
    # LoopCount is not always saved in the file, so burst mode is also detected
    # by size: more samples than presamples + postsamples.
    post = settings["PostTriggerSamples"]
    burst = 0
    by_number, by_name = {}, {}
    for ch in settings["CaptureChannels"]:
        raw = ch.get("Samples")
        if raw is None:
            continue
        samples = base64.b64decode(raw) if isinstance(raw, str) else bytes(raw)
        number = ch["ChannelNumber"] + 1          # starts at 0 in the file
        by_number[number] = samples
        if len(samples) > pre + post:
            burst = post
        name = (ch.get("ChannelName") or "").strip().upper()
        if name:
            by_name[name] = samples
    return freq, pre, burst, by_number, by_name


def load_csv(path):
    """.csv file = File > Export. Has no frequency, only 0/1 per column."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    header = [h.strip() for h in rows[0]]
    cols = list(zip(*rows[1:]))
    by_number, by_name = {}, {}
    for i, h in enumerate(header):
        samples = bytes(int(v) for v in cols[i])
        if h.upper().startswith("CHANNEL "):
            # The CSV numbers by column order, not by physical channel.
            # Works if the selected channels are 1..11 in sequence.
            by_number[int(h.split()[1])] = samples
        else:
            by_name[h.upper()] = samples
            by_number[i + 1] = samples
    return by_number, by_name


def pick_signals(by_number, by_name):
    sig = {}
    for s in SIGNALS:
        if s in by_name:
            sig[s] = by_name[s]
        elif DEFAULT_MAP[s] in by_number:
            sig[s] = by_number[DEFAULT_MAP[s]]
    missing = [s for s in ("E", "RS") if s not in sig]
    if missing:
        sys.exit(f"Signals {missing} are missing from the capture.")
    return sig


# ---------------------------------------------------------------------------
# Translating the commands
# ---------------------------------------------------------------------------

def describe_command(b):
    if b & 0x80:
        return f"Set DDRAM addr 0x{b & 0x7F:02X}"
    if b & 0x40:
        return f"Set CGRAM addr 0x{b & 0x3F:02X}"
    if b & 0x20:
        return ("Function set: " + ("8 bits" if b & 0x10 else "4 bits") + ", "
                + ("2 lines" if b & 0x08 else "1 line") + ", "
                + ("5x10" if b & 0x04 else "5x8"))
    if b & 0x10:
        return ("Shift " + ("display" if b & 0x08 else "cursor") + " to the "
                + ("right" if b & 0x04 else "left"))
    if b & 0x08:
        return ("Display " + ("ON" if b & 0x04 else "OFF")
                + ", cursor " + ("ON" if b & 0x02 else "OFF")
                + ", blink " + ("ON" if b & 0x01 else "OFF"))
    if b & 0x04:
        return ("Entry mode: " + ("increment" if b & 0x02 else "decrement")
                + (", shift display" if b & 0x01 else ""))
    if b & 0x02:
        return "Return home"
    if b & 0x01:
        return "Clear display"
    return "NOP (0x00)"


class Lcd:
    """Simplified copy of the HD44780's memory, to rebuild the screen."""

    def __init__(self):
        self.ddram = [0x20] * 0x80      # 0x00-0x27 = line 1, 0x40-0x67 = line 2
        self.addr = 0
        self.inc = 1
        self.shift = 0                  # display offset (shift command)
        self.cgram_mode = False
        self.eight_bit = True

    def command(self, b):
        if b & 0x80:
            self.addr, self.cgram_mode = b & 0x7F, False
        elif b & 0x40:
            self.cgram_mode = True
        elif b & 0x20:
            self.eight_bit = bool(b & 0x10)
        elif b & 0x10:
            if b & 0x08:
                self.shift += -1 if b & 0x04 else 1
        elif b & 0x08:
            pass                              # Display on/off: doesn't change the text
        elif b & 0x04:
            self.inc = 1 if b & 0x02 else -1
        elif b & 0x02:
            self.addr, self.shift, self.cgram_mode = 0, 0, False
        elif b & 0x01:
            self.ddram = [0x20] * 0x80
            self.addr, self.shift, self.inc, self.cgram_mode = 0, 0, 1, False

    def data(self, b):
        if self.cgram_mode:
            return                      # custom character: ignored
        self.ddram[self.addr] = b
        a = self.addr + self.inc
        # The HD44780 jumps from 0x27 to 0x40 and from 0x67 to 0x00.
        if a == 0x28:
            a = 0x40
        elif a == 0x68:
            a = 0x00
        elif a == 0x3F:
            a = 0x27
        elif a == -1:
            a = 0x67
        self.addr = a & 0x7F

    def screen(self):
        lines = []
        for base in (0x00, 0x40):
            row = ""
            for col in range(16):
                b = self.ddram[base + (col + self.shift) % 40]
                row += chr(b) if 0x20 <= b < 0x7F else "·"
            lines.append(row)
        return lines


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def decode(sig, freq, pre):
    e = sig["E"]
    n = len(e)
    us = 1e6 / freq
    data_bits = [sig.get(f"D{i}") for i in range(8)]

    def byte_at(i, bits):
        v = 0
        for k, ch in bits:
            if ch is not None and ch[i]:
                v |= 1 << k
        return v

    events = []
    falls = []
    rise = None
    widths = []
    for i in range(1, n):
        if e[i] and not e[i - 1]:
            rise = i
        elif e[i - 1] and not e[i]:
            j = i - 1                   # last sample with E high: data stable
            if rise is not None:
                widths.append(i - rise)
            rs = sig["RS"][j]
            rw = sig["RW"][j] if "RW" in sig else 0
            full = byte_at(j, list(enumerate(data_bits)))
            nib = byte_at(j, [(k - 4, data_bits[k]) for k in range(4, 8)])
            events.append(((i - pre) * us, rs, rw, full, nib))
            falls.append(i)

    # Idle: how each wire sits when the controller is NOT writing.
    # Looks at the middle of each long gap (> 200 µs) without pulses on E,
    # including before the first pulse and after the last.
    idle = []
    min_gap = int(200 / us)
    bounds = [0] + falls + [n - 1]
    for a, b in zip(bounds, bounds[1:]):
        if b - a > min_gap:
            m = (a + b) // 2
            idle.append((e[m], sig["RS"][m], sig["RW"][m] if "RW" in sig else 0,
                         byte_at(m, list(enumerate(data_bits)))))
    return events, widths, us, idle


def report_idle(idle):
    if not idle:
        print("Idle: no long gaps without writes in this capture.\n")
        return
    print(f"Idle (wire levels between writes, {len(idle)} gaps):")
    counts = {}
    for state in idle:
        counts[state] = counts.get(state, 0) + 1
    for (e, rs, rw, d), c in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  E={e} RS={rs} RW={rw} data=0x{d:02X}  ({c}x)")
    datas = {d for (_, _, _, d) in idle}
    if datas == {0xFF}:
        print("  -> the data lines all sit at 1 (floating) when idle.")
    else:
        print("  -> the data lines do NOT go back to 0xFF when idle (they hold some value).")
    print()


def run(events, widths, us, show_all, burst=0):
    lcd = Lcd()
    if not events:
        print("No falling edges on E. Check the CH1 (E) wiring.")
        return

    reads = sum(1 for ev in events if ev[2])
    print(f"Falling edges on E: {len(events)}   reads (RW=1): {reads}")
    if widths:
        print(f"E pulse width: min {min(widths) * us:.2f} µs, "
              f"max {max(widths) * us:.2f} µs "
              f"({min(widths)} samples in the shortest)")
        if min(widths) < 3:
            print("  WARNING: the shortest pulse has fewer than 3 samples. "
                  "Raise the capture frequency.")
    print()

    pending_nibble = None
    text_run = ""
    text_start = None
    last_t = None

    def flush_text():
        nonlocal text_run, text_start
        if text_run:
            print(f"{text_start:12.1f} µs  DATA  \"{text_run}\"")
            text_run, text_start = "", None

    def show_screen():
        l1, l2 = lcd.screen()
        print("              ┌────────────────┐")
        print(f"              │{l1}│")
        print(f"              │{l2}│")
        print("              └────────────────┘")

    current_burst = 0
    for t, rs, rw, full, nib in events:
        if burst:
            b = max(0, int(round(t / us)) // burst)
            if b != current_burst:
                flush_text()
                show_screen()
                print(f"=== stretch {b + 1} (new trigger; the idle time before it was not recorded) ===")
                current_burst, last_t = b, None
        if last_t is not None and t - last_t > BURST_GAP_US:
            flush_text()
            show_screen()
            print(f"--- pause of {(t - last_t) / 1000:.1f} ms ---")
        last_t = t

        if rw:
            flush_text()
            print(f"{t:12.1f} µs  READ RS={rs} value=0x{full:02X}"
                  + ("  (busy flag = 1)" if (rs == 0 and full & 0x80) else ""))
            continue

        # 4-bit mode: each byte arrives in two halves (high one first).
        if not lcd.eight_bit:
            if pending_nibble is None:
                pending_nibble = (rs, nib)
                continue
            value = (pending_nibble[1] << 4) | nib
            pending_nibble = None
        else:
            value = full

        if rs:
            if text_start is None:
                text_start = t
            text_run += chr(value) if 0x20 <= value < 0x7F else f"\\x{value:02X}"
            lcd.data(value)
        else:
            flush_text()
            if show_all or value != 0x00:
                print(f"{t:12.1f} µs  CMD 0x{value:02X}  {describe_command(value)}")
            lcd.command(value)

    flush_text()
    print("\nFinal screen:")
    show_screen()


def main():
    ap = argparse.ArgumentParser(description="Decodes the HD44780 bus from a LogicAnalyzer capture.")
    ap.add_argument("arquivo", metavar="file", help=".lac capture (recommended) or .csv")
    ap.add_argument("--freq", type=int, help="capture frequency in Hz (required for .csv)")
    ap.add_argument("--all", "--todos", dest="todos", action="store_true", help="also show 0x00 commands")
    ap.add_argument("--no-rw", "--sem-rw", dest="sem_rw", action="store_true",
                    help="use when the RW wire failed: treats RS=0 with a value < 0x80 as a read "
                         "(holds outside initialization, where there are only 'Set DDRAM' and characters)")
    args = ap.parse_args()

    if args.arquivo.lower().endswith(".lac"):
        freq, pre, burst, by_number, by_name = load_lac(args.arquivo)
    else:
        if not args.freq:
            sys.exit("For .csv give the frequency, for example: --freq 10000000")
        by_number, by_name = load_csv(args.arquivo)
        freq, pre, burst = args.freq, 0, 0

    sig = pick_signals(by_number, by_name)
    print(f"File: {args.arquivo}   frequency: {freq / 1e6:g} MHz   "
          f"samples: {len(sig['E'])}   signals: {', '.join(s for s in SIGNALS if s in sig)}\n")

    # A wire that never changes while E pulses is probably loose
    # or on the wrong pin (real text makes almost every bit change).
    stuck = [f"{s}={sig[s][0]}" for s in SIGNALS
             if s != "E" and s in sig and len(set(sig[s])) == 1]
    if stuck and len(set(sig["E"])) > 1:
        print("WARNING: these wires stayed still during the whole capture: " + ", ".join(stuck))
        print("  That can be normal for one or two, but several still ones point to a loose or misplaced wire.\n")
    events, widths, us, idle = decode(sig, freq, pre)
    report_idle(idle)
    if args.sem_rw:
        events = [(t, rs, 1 if (rs == 0 and full < 0x80) else 0, full, nib)
                  for t, rs, rw, full, nib in events]
    run(events, widths, us, args.todos, burst)


if __name__ == "__main__":
    main()
