"""Draws the SP103 screens from a state (the reverse of amp_state.parse).

Formats taken from the captures (docs/descobertas-protocolo.md). Those marked
"guess" have not been seen on the amp yet.
"""

BOX = "\x00"

# Custom characters the controller stores when it powers up (CGRAM).
CGRAM = [
    [0x00, 0x1F, 0x11, 0x11, 0x11, 0x11, 0x1F, 0x00],     # 0: empty box (bars)
] + [
    [0x1F if row >= 8 - n else 0x00 for row in range(8)]  # 1..7: bars n rows tall
    for n in range(1, 8)
]


def _pad(text):
    return (text + " " * 16)[:16]


def volume_line(db):
    # "Volume -28.75 dB". With a single digit ("-5.00"), guess: right-aligned.
    return _pad("Volume" + ("%7.2f" % db) + " dB")


def normal(volume_db, input_name):
    return volume_line(volume_db), _pad(input_name)


def volume_bar(volume_db):
    # 10 boxes at -28.75 dB: proportional to (78.75 + dB) / 78.75 of the 16 columns.
    n = int((78.75 + volume_db) / 78.75 * 16)
    return volume_line(volume_db), _pad(BOX * n)


def bipolar_bar(left, right):
    """Bar with '<>' in columns 7 and 8 and boxes packed against one side."""
    return _pad(" " * (7 - left) + BOX * left + "<>" + BOX * right)


def tone(word, db):
    """Bass or Treble: 'Bass   2 dB', 'Bass -10 dB'. One box every 2 dB."""
    n = abs(db) // 2
    bar = bipolar_bar(n, 0) if db < 0 else bipolar_bar(0, n)
    return _pad(word + ("%4d" % db) + " dB"), bar


def balance(side, db):
    if side is None and db == 0:
        return _pad("Balance <level>"), bipolar_bar(0, 0)
    n = int(-db // 5)                   # one box every 5 dB
    bar = bipolar_bar(n, 0) if side == "L" else bipolar_bar(0, n)
    return _pad("Balance" + ("%6.2f" % db) + " dB"), bar


def choice(word, on):
    # Seen: Loudness OFF and Speakers ON. The other two cases are a guess.
    line2 = "   OFF   < ON > " if on else " < OFF >   ON   "
    return _pad("   " + word), line2


def boot():
    return "    ACOUSTIC    ", "    SOLUTIONS   "


def about(version="1.0"):
    return "Amplifier SP103 ", _pad(" SW version " + version)
