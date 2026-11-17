"""GET /device: who this bridge is and what it can do.

The contract is in the amp-link repository (docs/contract-v1.md). Everything here is fixed while the program
runs: the client reads it once on connecting. The version is the same as GET /update's.

describe() runs the same in MicroPython (Pico) and in the computer's Python (tools/test_device.py).
"""

from amp_state import INPUTS, INPUT_IDS, STEP, VOLUME_MIN

API = 1                         # only changes when something stops being compatible
MODEL = "Acoustic Solutions SP103"
TONE_DB = 14                    # bass and treble: from -14 to 14
TONE_STEP = 2                   # each press on the amp changes 2 dB
COLUMNS, ROWS = 16, 2
FEATURES = ("tone", "balance", "loudness", "speakers", "config", "vu", "info_screens", "bus_log", "update", "wifi_setup",
            "control")


def describe(version):
    return {"api": API, "model": MODEL, "bridge_version": version,
            "volume_db": {"min": VOLUME_MIN, "max": 0, "step": STEP},
            "tone_db": {"min": -TONE_DB, "max": TONE_DB, "step": TONE_STEP},
            "inputs": [{"id": INPUT_IDS[name], "name": name} for name in INPUTS],
            "display": {"columns": COLUMNS, "rows": ROWS},
            "features": list(FEATURES)}


async def handle(req, writer):
    """/device route (see web.Publisher)."""
    import ota
    from web import reply, reply_json
    if req.path != "/device":
        return await reply(writer, "404 Not Found", "text/plain", b"not found\n")
    await reply_json(writer, describe(await ota.current_version()))
