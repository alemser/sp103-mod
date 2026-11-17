#!/usr/bin/env python3
"""Reads the CSV downloaded from http://sp103.local/bus.csv and rebuilds the amp's screens, with timestamps.

    python3 tools/ler_bus.py ~/Downloads/sp103-bus-2026-10-24-2115.csv
    python3 tools/ler_bus.py file.csv --words           # also every word, one per line

Uses the Pico's own hd44780.Bus (firmware/hd44780.py), so it shows what the Pico saw.
The start of the file usually lands in the middle of a screen (the log keeps only the last
words); the first complete screen comes right after.
"""

import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))

from amp_state import lcd_text   # noqa: E402
from hd44780 import Bus, DATA_SHIFT, RS, RW   # noqa: E402

QUIET_MS = 5        # the Pico reads in ~1 ms batches; consecutive screens are much further apart than that


def words(path):
    """(time, ms, word) for each CSV row."""
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            word = int(row["byte"], 16) << DATA_SHIFT
            word |= (RS if row["rs"] == "1" else 0) | (RW if row["rw"] == "1" else 0) | 1
            yield row["time"], int(row["ms"]), word


def screens(rows):
    """(time, line 1, line 2) for each complete screen."""
    bus, last, out = Bus(), None, []
    for when, ms, word in rows:
        if bus.pending and last is not None and ms - last[1] > QUIET_MS:
            out.append((last[0] or "%d ms" % last[1],) + bus.take())
        bus.feed(word)
        last = (when, ms)
    if bus.pending:
        out.append((last[0] or "%d ms" % last[1],) + bus.take())
    return out, bus


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv")
    ap.add_argument("--words", "--palavras", dest="palavras", action="store_true", help="also show every word")
    args = ap.parse_args()

    if args.palavras:
        with open(args.csv, newline="") as f:
            for row in csv.DictReader(f):
                print("%-23s %10s  %s" % (row["time"], row["ms"], row["meaning"]))
        print()

    got, bus = screens(words(args.csv))
    for when, l1, l2 in got:
        print("%-23s  %s | %s" % (when, lcd_text(l1), lcd_text(l2)))
    print("\n%d screens, %d writes, %d busy flag reads, %d 'clear display' (amp powering on)" % (
        len(got), bus.writes, bus.reads, bus.clears))


if __name__ == "__main__":
    main()
