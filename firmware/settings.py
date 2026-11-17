"""What a person may change on the bridge (names.json, see names.py), over HTTP.

    GET   /settings   {"<id>": value, ...}                    (contract v2: amp-link docs/contract-v2.md, Settings)
    PATCH /settings   only the ids that change; answers the whole object, or 400 {"error", "id"}

The ids flatten names.json: "inputs.TUNER", "boot.0", "vu.on", "info.show.stylus", "info.turntable.PHONO". FIELDS is
the description's "settings" list (device.py). to_flat() and patch() run the same on the Pico and on the computer
(tools/test_settings.py).
"""

import json

import names
from amp_state import INPUTS

DEFAULTS = {"boot": ["ACOUSTIC", "SOLUTIONS"], "about": ["Amplifier SP103", "SW version 1.0"]}   # the amp's own
INFO_MODES = ("temp", "fixed")


def _field(fid, ftype, label, group, **extra):
    d = {"id": fid, "type": ftype, "label": label, "group": group}
    d.update(extra)
    return d


def _lcd(fid, label, group):
    return _field(fid, "text", label, group, max=names.MAX_LEN, charset="lcd")


FIELDS = [_lcd("inputs." + i, i, "Input names") for i in INPUTS]
for _screen, _group in (("boot", "Boot screen"), ("about", "About screen")):
    FIELDS += [_lcd("%s.%d" % (_screen, n), "Line %d (%s)" % (n + 1, DEFAULTS[_screen][n]), _group) for n in (0, 1)]
FIELDS += [
    _field("vu.on", "bool", "VU meter while music plays", "VU meter"),
    _field("vu.layout", "enum", "Layout", "VU meter", values=list(names.VU_LAYOUTS)),
    _field("vu.relay", "ip", "Source (the VU relay's IP)", "VU meter"),
    _field("info.on", "bool", "Info screens", "Info screens"),
    _field("info.mode", "enum", "Show them", "Info screens", values=list(INFO_MODES),
           labels=["For a few seconds", "All the time"]),
    _field("info.show.stylus", "bool", "Stylus hours (turntable inputs)", "Info screens"),
    _field("info.show.quality", "bool", "Bluetooth quality (DAB)", "Info screens"),
    _field("info.secs", "int", "Seconds on screen", "Info screens", min=names.INFO_SECS[0], max=names.INFO_SECS[1],
           step=1),
    _field("info.source", "ip", "Source (IP; empty = the VU's)", "Info screens"),
]
FIELDS += [_field("info.turntable." + i, "bool", i, "Turntable inputs") for i in INPUTS]
TYPES = {f["id"]: f for f in FIELDS}


class SettingError(ValueError):
    def __init__(self, fid, message):
        super().__init__(message)
        self.id = fid


def to_flat(cfg):
    """names.json (validated) -> {"<id>": value} for every field."""
    vu, info = cfg["vu"], cfg["info"]
    out = {}
    for i in INPUTS:
        out["inputs." + i] = cfg["inputs"].get(i, "")
    for screen in ("boot", "about"):
        for n in (0, 1):
            out["%s.%d" % (screen, n)] = cfg[screen][n]
    out["vu.on"], out["vu.layout"], out["vu.relay"] = vu["on"], vu["layout"], vu["relay"]
    out["info.on"], out["info.mode"], out["info.secs"] = info["on"], info["mode"], info["secs"]
    out["info.source"] = info["source"]
    for kind in names.INFO_KINDS:
        out["info.show." + kind] = kind in info["show"]
    for i in INPUTS:
        out["info.turntable." + i] = i in info["turntable"]
    return out


def _check(fid, value):
    f = TYPES.get(fid)
    if f is None:
        raise SettingError(fid, "unknown setting: %s" % fid)
    t = f["type"]
    ok = (isinstance(value, bool) if t == "bool"
          else isinstance(value, int) and not isinstance(value, bool) if t == "int"
          else value in f["values"] if t == "enum"
          else isinstance(value, str))
    if not ok:
        raise SettingError(fid, "%s: %s" % (f["label"], "must be one of " + ", ".join(f["values"]) if t == "enum"
                                            else "must be " + {"bool": "true or false", "int": "a whole number"}
                                            .get(t, "text")))


def _toggle(items, item, on):
    if on and item not in items:
        items.append(item)
    elif not on and item in items:
        items.remove(item)


def patch(cfg, changes):
    """A new, validated names.json: cfg with only `changes` ({"<id>": value}) applied. Raises SettingError (or
    ValueError, from names.validate) and leaves cfg untouched."""
    if not isinstance(changes, dict):
        raise ValueError("the settings must be a JSON object")
    new = json.loads(json.dumps(cfg))
    for fid, value in changes.items():
        _check(fid, value)
        head, _, rest = fid.partition(".")
        if head == "inputs":
            new["inputs"][rest] = value
        elif head in ("boot", "about"):
            new[head][int(rest)] = value
        elif rest.startswith("show."):
            _toggle(new["info"]["show"], rest[5:], value)
        elif rest.startswith("turntable."):
            _toggle(new["info"]["turntable"], rest[10:], value)
        else:
            new[head][rest] = value
    try:
        return names.validate(new)
    except ValueError as e:
        if len(changes) == 1:
            raise SettingError(next(iter(changes)), str(e))
        raise


class Routes:
    """/settings. get_cfg() gives the current names.json; apply(cfg) saves and applies a valid one."""

    def __init__(self, get_cfg, apply):
        self.get_cfg = get_cfg
        self.apply = apply

    async def handle(self, req, writer):
        from web import reply, reply_json
        body = await req.reader.readexactly(req.length) if req.length else b""
        if req.path != "/settings":
            return await reply(writer, "404 Not Found", "text/plain", b"not found\n")
        error = None
        try:
            if req.method == "PATCH":
                self.apply(patch(self.get_cfg(), json.loads(body)))
        except SettingError as e:
            error = {"error": str(e), "id": e.id}
        except ValueError as e:         # invalid JSON, or text refused by names.validate
            error = {"error": str(e)}
        if error:
            return await reply_json(writer, error, "400 Bad Request")
        await reply_json(writer, to_flat(self.get_cfg()))
