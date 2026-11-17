"""SP103 screen reader: turns the 2 LCD lines into the amplifier's state.

Runs the same on MicroPython (Pico) and on the computer's Python (tests).

Use:
    st = AmpState()
    if st.update(linha1, linha2, agora_ms):
        print(st.to_dict())      # something changed

The lines are the 16 positions of each LCD line, with the original codes
(chr(0) = the bar box, see docs/descobertas-protocolo.md).

IMPORTANT: only call update() with the COMPLETE screen. The controller redraws
character by character (about 8.5 ms per screen), and halfway through a line
can mix the old value with the new one ("Volume -27.75" instead of "-27.50").
The sniffer must wait a few milliseconds without writes before calling.

Standby: on going to standby, the controller writes spaces to all 32 positions (seen on
2026-10-29), and "power" becomes "standby"; on leaving it, it draws the normal screen
directly. When mains power arrives the screen is also blank, but preceded by a "Clear
display": that is why update() gets cleared=True in that case, and the blank screen does
not count as standby. power = None: not known yet (the Pico has just started).
"""

BOX = "\x00"                    # custom character 0: the bar box
INPUTS = ("PHONO", "TUNER", "TAPE/AUX", "CD", "DVD", "DAB")
STREAMING_INPUT = "DAB"         # chosen by the owner: the input wired to streaming (AirPlay, Bluetooth)
# Stable lowercase identifiers for API clients.
INPUT_IDS = {"PHONO": "phono", "TUNER": "tuner", "TAPE/AUX": "tape_aux",
             "CD": "cd", "DVD": "dvd", "DAB": "dab"}
VOLUME_MIN = -78.75             # PT2314: 0 to -78.75 dB, 1.25 dB steps
STEP = 1.25
SPEAKERS_AFTER_STANDBY = True   # measured on 2026-11-06: speakers always goes back to ON on leaving standby

# The state fields, in the order they appear in the JSON.
FIELDS = ("power", "volume_db", "input", "input_id", "input_name", "bass_db", "treble_db", "balance",
          "loudness", "speakers", "screen", "firmware", "lcd", "updated_at")


def _db(text):
    """'-28.75' -> -28.75, or None if it is not a valid number."""
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        return None


def _is_step(v, lo, hi):
    """Checks that v is between lo and hi and is a multiple of 1.25 dB."""
    if v is None or v < lo or v > hi:
        return False
    k = v / STEP
    return abs(k - round(k)) < 0.001


def _ends_db(line):
    """Strips ' dB' from the end of the line, or returns None if it does not end that way."""
    line = line.rstrip()
    if not line.endswith(" dB"):
        return None
    return line[:-3]


def _bar(line):
    """Bipolar bar on line 2: '<>' at columns 7 and 8, boxes on one side.

    Returns (left_boxes, right_boxes), or None if the line is not a bar.
    """
    if line[7:9] != "<>":
        return None
    left, right = line[:7], line[9:]
    for part in (left, right):
        for c in part:
            if c != BOX and c != " ":
                return None
    # The boxes sit right against the "<>": on the left they end at column 6, on the right they start at 9.
    nl = len(left) - len(left.rstrip(BOX))
    nr = len(right) - len(right.lstrip(BOX))
    if left.count(BOX) != nl or right.count(BOX) != nr:
        return None
    return nl, nr


def _choice(line):
    """Line 2 of Loudness/Speakers: 'OFF' and 'ON', the chosen one between '< >'.

    Returns True (ON), False (OFF) or None.
    """
    a, b = line.find("<"), line.find(">")
    if a < 0 or b < a or line.count("<") != 1 or line.count(">") != 1:
        return None
    chosen = line[a + 1:b].strip()
    rest = (line[:a] + " " + line[b + 1:]).split()
    if chosen == "ON" and rest == ["OFF"]:
        return True
    if chosen == "OFF" and rest == ["ON"]:
        return False
    return None


def parse(line1, line2):
    """Recognises a complete screen.

    Returns (screen_name, {field: value}) with only the fields the screen shows,
    or ("unknown", {}) if the screen is not recognised.
    """
    l1, l2 = line1, line2

    # Normal or volume screen: "Volume -28.75 dB"
    if l1.startswith("Volume "):
        v = _ends_db(l1[7:])
        v = _db(v) if v is not None else None
        if not _is_step(v, VOLUME_MIN, 0):
            return "unknown", {}
        name = l2.rstrip()
        if name in INPUTS:
            return "normal", {"volume_db": v, "input": name}
        # Volume bar: boxes from column 0, then only spaces.
        boxes = l2.rstrip(" ")
        if boxes == BOX * len(boxes):
            return "volume", {"volume_db": v}
        return "unknown", {}

    # Bass and Treble: "Bass   2 dB", "Bass -10 dB", "Treble   0 dB" (no '+')
    for word, field in (("Bass", "bass_db"), ("Treble", "treble_db")):
        if l1.startswith(word + " "):
            v = _ends_db(l1[len(word):])
            v = _db(v) if v is not None else None
            bar = _bar(l2)
            if v is None or v != int(v) or abs(v) > 14 or bar is None:
                return "unknown", {}
            nl, nr = bar
            # Each box is worth 2 dB: the bar must agree with the number.
            if (v < 0 and (nr or nl != int(-v) // 2)) or (v > 0 and (nl or nr != int(v) // 2)) \
                    or (v == 0 and (nl or nr)):
                return "unknown", {}
            return word.lower(), {field: int(v)}

    # Balance: "Balance -5.00 dB", "Balance-10.00 dB"; centred: "Balance <level>"
    if l1.startswith("Balance"):
        bar = _bar(l2)
        if bar is None:
            return "unknown", {}
        nl, nr = bar
        if l1.rstrip() == "Balance <level>":
            if nl or nr:
                return "unknown", {}
            return "balance", {"balance": {"side": None, "db": 0.0}}
        v = _ends_db(l1[7:])
        v = _db(v) if v is not None else None
        if not _is_step(v, VOLUME_MIN, -STEP):
            return "unknown", {}
        # One box every 5 dB, on the bar's side. The number does not tell the side.
        if (nl and nr) or (nl + nr) != int(-v // 5):
            return "unknown", {}
        if nl == 0 and nr == 0:
            side = None             # under 5 dB: the bar does not show yet
        else:
            side = "L" if nl else "R"
        return "balance", {"balance": {"side": side, "db": v}}

    if l1.strip() == "Loudness":
        on = _choice(l2)
        if on is None:
            return "unknown", {}
        return "loudness", {"loudness": on}

    if l1.strip() == "Speakers":
        on = _choice(l2)
        if on is None:
            return "unknown", {}
        return "speakers", {"speakers": on}

    if l1.strip() == "ACOUSTIC" and l2.strip() == "SOLUTIONS":
        return "boot", {}

    if l1.strip() == "Amplifier SP103" and l2.strip().startswith("SW version "):
        return "about", {"firmware": l2.strip()[len("SW version "):]}

    return "unknown", {}


def lcd_text(line):
    """An LCD line as readable text: the box becomes '■', other codes become '·'."""
    out = ""
    for c in line:
        if c == BOX:
            out += "■"
        elif " " <= c <= "~":
            out += c
        else:
            out += "·"
    return out


class AmpState:
    """The amplifier's state, built from the screens the controller draws."""

    def __init__(self, names=None):
        self.names = names or {}    # name table (names.py): {"TUNER": "Rega Planar 2"}
        self.power = None           # "on" (recognised screen), "standby" (blank screen) or None
        self.volume_db = None
        self.input = None           # original name on the amp: "TUNER"
        self.input_id = None        # stable input identifier: "tuner"
        self.input_name = None      # name from the table, or the original: "Rega Planar 2"
        self.bass_db = None
        self.treble_db = None
        self.balance = None         # {"side": "L"/"R"/None, "db": -5.0}
        self.loudness = None
        self.speakers = None
        self.screen = None
        self.firmware = None
        self.lcd = ["", ""]
        self.updated_at = None      # milliseconds (the caller's clock)
        self.version = 0            # goes up on every change (useful for /events)

    def update(self, line1, line2, now_ms=None, cleared=False):
        """Reads a complete screen. Returns True if any field changed.

        cleared: there was a "Clear display" since the previous screen (the amp is powering up)."""
        screen, values = parse(line1, line2)
        if not cleared and not (line1 + line2).strip(" "):
            screen = "standby"
        changed = False
        lcd = [lcd_text(line1), lcd_text(line2)]
        if lcd != self.lcd:
            self.lcd = lcd
            changed = True
        if screen != self.screen:
            self.screen = screen
            changed = True
        power = "standby" if screen == "standby" else "on" if screen != "unknown" else self.power
        if power != self.power:
            if self.power == "standby" and power == "on" and self.speakers != SPEAKERS_AFTER_STANDBY:
                self.speakers = SPEAKERS_AFTER_STANDBY
            self.power = power
            changed = True
        for key in values:
            if getattr(self, key) != values[key]:
                setattr(self, key, values[key])
                changed = True
        if self._names_changed():
            changed = True
        if changed:
            self.version += 1
            self.updated_at = now_ms
        return changed

    def set_names(self, names, now_ms=None):
        """Replaces the name table. Returns True if input_name changed."""
        self.names = names
        if self._names_changed():
            self.version += 1
            self.updated_at = now_ms
            return True
        return False

    def _names_changed(self):
        if self.input is None:
            return False
        iid, name = INPUT_IDS[self.input], self.names.get(self.input, self.input)
        if (iid, name) == (self.input_id, self.input_name):
            return False
        self.input_id, self.input_name = iid, name
        return True

    def to_dict(self):
        d = {}
        for key in FIELDS:
            d[key] = getattr(self, key)
        d["version"] = self.version
        return d
