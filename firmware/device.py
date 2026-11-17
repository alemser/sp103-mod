"""GET /device: who this bridge is and what it can do, in the DeviceLink contract api 2 (amp-link docs/contract-v2.md).

The app builds the SP103's screen from this: the state fields to show, the remote in groups (power, volume, input,
tone, switches) and the settings (settings.py). The JSON is built on the first request and served as stored bytes
afterwards; only a change to the input names rebuilds it (the input chips carry the names the person chose).

/state keeps the contract v1 fields (volume_db, input_id, bass_db...), which groove-rig also reads.

describe() runs the same in MicroPython (Pico) and in the computer's Python (tools/test_device.py).
"""

import json

import settings
from amp_state import INPUTS, INPUT_IDS

API = 2                         # only changes when something stops being compatible
NAME = "sp103"                  # the discovery and network name (sp103.local, AmpLink-SP103-XXXX); enviar.py reads it
KIND = "amplifier"
MODEL = "Acoustic Solutions SP103"
FIRMWARE = "alemser/sp103-mod"  # the GitHub repository whose releases carry this firmware (enviar.py --publish)
FEATURES = ("control", "settings", "update", "wifi_setup")

STATE = (
    {"id": "power", "type": "enum", "values": ["on", "standby"]},
    {"id": "lcd", "type": "lines", "label": "Display"},
    {"id": "volume_db", "type": "number", "label": "Volume", "unit": "dB"},
    {"id": "input_name", "type": "text", "label": "Input"},
    {"id": "bass_db", "type": "number", "label": "Bass", "unit": "dB"},
    {"id": "treble_db", "type": "number", "label": "Treble", "unit": "dB"},
    {"id": "balance.db", "type": "number", "label": "Balance", "unit": "dB"},
    {"id": "loudness", "type": "bool", "label": "Loudness"},
    {"id": "speakers", "type": "bool", "label": "Speakers"},
)

CONTROLS = (
    {"group": "power", "keys": ["power_toggle"]},
    {"group": "volume", "steps": [{"target": "volume", "state": "volume_db", "label": "Volume"}]},
    {"group": "input", "select": {"state": "input_id", "options": []}},     # filled by describe(), with the names
    {"group": "tone", "steps": [{"target": "bass", "state": "bass_db", "label": "Bass"},
                                {"target": "treble", "state": "treble_db", "label": "Treble"},
                                {"target": "balance", "state": "balance.db", "label": "Balance"}]},
    {"group": "modes", "switches": [{"target": "loudness", "state": "loudness", "label": "Loudness"},
                                    {"target": "speakers", "state": "speakers", "label": "Speakers"}]},
)

net = None                      # proxy.py sets it: the discovery name comes from the chip ("SP103-D4FE")
input_names = None              # proxy.py sets it: () -> names.json "inputs" ({"TUNER": "Rega Planar 2"})
_cached = None


def forget():
    """The input names changed (proxy.set_texts): the next GET /device rebuilds the description."""
    global _cached
    _cached = None


def describe(version, name, custom=None):
    custom = custom or {}
    options = [{"id": INPUT_IDS[i], "name": custom.get(i) or i, "key": "select_" + INPUT_IDS[i]} for i in INPUTS]
    controls = []
    for g in CONTROLS:
        if "select" in g:               # a copy: the template stays empty (no dict(g, **kw) on MicroPython)
            g = {"group": g["group"], "select": {"state": g["select"]["state"], "options": options}}
        controls.append(g)
    return {"api": API, "kind": KIND, "model": MODEL, "name": name, "bridge_version": version,
            "firmware": FIRMWARE, "features": list(FEATURES), "state": list(STATE), "controls": controls,
            "settings": settings.FIELDS}


def keys():
    """Every key the description sends (tools/test_device.py checks the IR sender knows them)."""
    out = []
    for group in describe("", "")["controls"]:
        out += group.get("keys", [])
        out += [o["key"] for o in group.get("select", {}).get("options", [])]
    return out


async def handle(req, writer):
    """Route /device (see web.Publisher)."""
    global _cached
    import ota
    from web import reply
    if req.path != "/device":
        return await reply(writer, "404 Not Found", "text/plain", b"not found\n")
    if _cached is None:
        custom = input_names() if input_names else None
        _cached = json.dumps(describe(await ota.current_version(), net.name if net else NAME, custom)).encode()
    await reply(writer, "200 OK", "application/json", _cached)
