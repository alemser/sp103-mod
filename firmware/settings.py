"""What a person may change on the display (names.json, see names.py), over HTTP: the SP103's own extras.

Not part of the DeviceLink contract (device-link docs/contract-v2.md), which carries only the device, its state and
its remote. The SP103's own page (config_page.py, http://<the Pico's IP>/) edits these; curl works too.

    GET   /settings          {"<id>": value, ...}
    PATCH /settings          only the ids that change; answers the whole object, or 400 {"error", "id"}
    GET   /settings/fields   what the page draws: fields(), below

The ids flatten names.json: "inputs.TUNER", "boot.0", "vu.on", "info.show.stylus", "info.turntable.PHONO". fields()
gives each one's type, label, group, hint, "when" (shown only while other settings have those values) and placeholder
(the amp's own text, when a text is empty). to_flat() and patch() run the same on the Pico and on the computer
(tools/test_device.py).
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


def _lcd(fid, label, group, **extra):
    return _field(fid, "text", label, group, max=names.MAX_LEN, charset="lcd", **extra)


VU_LAYOUT_NAMES = {"bars": "Thin bars", "deck": "Cassette deck", "scale": "Printed scale", "kx393": "Yamaha KX-393"}
INFO_ON = {"info.on": True}


def fields(custom=None):
    """The page's field list. custom = names.json "inputs": the turntable choices carry the chosen names."""
    custom = custom or {}
    out = [_lcd("inputs." + i, i, "Input names", placeholder=i) for i in INPUTS]
    out[0]["hint"] = "Empty = the amp's own name. Up to 16 characters, no accents"
    for screen, group in (("boot", "Boot screen"), ("about", "About screen")):
        out += [_lcd("%s.%d" % (screen, n), "Line %d" % (n + 1), group, placeholder=DEFAULTS[screen][n]) for n in (0, 1)]
    out += [
        _field("vu.on", "bool", "VU meter while music plays", "VU meter"),
        _field("vu.layout", "enum", "Layout", "VU meter", values=list(names.VU_LAYOUTS),
               labels=[VU_LAYOUT_NAMES[k] for k in names.VU_LAYOUTS], when={"vu.on": True}),
        _field("vu.relay", "ip", "Source (the VU relay's IP)", "VU meter",
               hint="The board running sp103-vu-relay; the Pico does not resolve .local names"),
        _field("info.on", "bool", "Stylus and Bluetooth quality", "Info screens"),
        _field("info.mode", "enum", "Show them", "Info screens", values=list(INFO_MODES),
               labels=["For a few seconds", "All the time"], when=INFO_ON,
               hint="All the time: the VU meter is not shown"),
        _field("info.secs", "int", "Seconds on the display", "Info screens", min=names.INFO_SECS[0],
               max=names.INFO_SECS[1], step=1, when={"info.on": True, "info.mode": "temp"},
               hint="Stylus: when you switch to a turntable input and when a record starts. Bluetooth: when it starts "
                    "or the quality changes"),
        _field("info.show.stylus", "bool", "Stylus hours", "Info screens", hint="On the turntable inputs", when=INFO_ON),
        _field("info.show.quality", "bool", "Bluetooth quality", "Info screens", hint="On DAB, with Bluetooth",
               when=INFO_ON),
        _field("info.source", "ip", "Info source (IP)", "Info screens", hint="Empty = the VU source", when=INFO_ON),
    ]
    turntable = [_field("info.turntable." + i, "bool", custom.get(i) or i, "Turntable inputs", when=INFO_ON)
                 for i in INPUTS]
    turntable[0]["hint"] = "The stylus screen only appears on these"
    return out + turntable


FIELDS = fields()
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
    """/settings and /settings/fields. get_cfg() gives the current names.json; apply(cfg) saves and applies a valid one."""

    def __init__(self, get_cfg, apply):
        self.get_cfg = get_cfg
        self.apply = apply

    async def handle(self, req, writer):
        from web import reply, reply_json
        body = await req.reader.readexactly(req.length) if req.length else b""
        if req.path == "/settings/fields":
            return await reply_json(writer, fields(self.get_cfg()["inputs"]))
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
