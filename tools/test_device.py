#!/usr/bin/env python3
"""Tests the bridge's description (firmware/device.py) and its settings (firmware/settings.py) on the computer.

    python3 tools/test_device.py
"""

import asyncio
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))

import device     # noqa: E402
import ir_codes   # noqa: E402
import names      # noqa: E402
import settings   # noqa: E402
from amp_state import INPUTS   # noqa: E402

d = json.loads(json.dumps(device.describe("abcd1234", "SP103-D4FE")))
assert d["api"] == 2 and d["kind"] == "amplifier" and d["name"] == "SP103-D4FE"
assert d["model"] == "Acoustic Solutions SP103" and d["firmware"] == "alemser/sp103-mod"
assert d["bridge_version"] == "abcd1234"
assert {"control", "settings", "update", "wifi_setup"} <= set(d["features"])
assert [g["group"] for g in d["controls"]] == ["power", "volume", "input", "tone", "modes"]
options = d["controls"][2]["select"]["options"]
assert [o["name"] for o in options] == list(INPUTS)
assert [o["id"] for o in options] == ["phono", "tuner", "tape_aux", "cd", "dvd", "dab"]
assert set(device.keys()) <= set(ir_codes.COMMANDS), "every key is one the IR sender knows"
named = device.describe("abcd1234", "SP103-D4FE", {"TUNER": "Rega Planar 2"})["controls"][2]["select"]["options"]
assert [o["name"] for o in named[:3]] == ["PHONO", "Rega Planar 2", "TAPE/AUX"], "the chips carry the chosen names"
assert named[1]["key"] == "select_tuner" and named[1]["id"] == "tuner"
assert device.CONTROLS[2]["select"]["options"] == [], "describe() does not change the template"
assert d["state"][0]["id"] == "power"
size = len(json.dumps(device.describe("abcd1234", "SP103-D4FE")))
assert size < 6000, "the description stays small: %d bytes" % size

# --- settings ------------------------------------------------------------------------------------------
ids = [f["id"] for f in d["settings"]]
assert len(ids) == len(set(ids)), "unique ids"
cfg = names.validate({"inputs": {"TUNER": "Rega Planar 2"}, "info": {"turntable": ["PHONO"]}})
flat = settings.to_flat(cfg)
assert sorted(flat) == sorted(ids), "every field has a value and every value a field"
assert flat["inputs.TUNER"] == "Rega Planar 2" and flat["inputs.CD"] == ""
assert flat["boot.0"] == "" and flat["vu.on"] is False and flat["info.secs"] == 8
assert flat["info.turntable.PHONO"] is True and flat["info.turntable.TUNER"] is False
assert flat["info.show.stylus"] is True

new = settings.patch(cfg, {"inputs.CD": "Yamaha", "info.show.stylus": False, "info.turntable.TUNER": True,
                           "info.secs": 12, "boot.1": "Alessandro"})
f2 = settings.to_flat(new)
assert f2["inputs.CD"] == "Yamaha" and f2["inputs.TUNER"] == "Rega Planar 2", "only what changes changes"
assert f2["info.show.stylus"] is False and f2["info.show.quality"] is True
assert f2["info.turntable.TUNER"] is True and f2["info.turntable.PHONO"] is True and f2["info.secs"] == 12
assert f2["boot.1"] == "Alessandro" and f2["boot.0"] == ""
assert settings.to_flat(cfg)["inputs.CD"] == "", "the old configuration is left untouched"
assert settings.to_flat(settings.patch(cfg, {"inputs.TUNER": ""}))["inputs.TUNER"] == "", "empty = the amp's name"


def refused(changes, fid):
    try:
        settings.patch(cfg, changes)
    except settings.SettingError as e:
        assert e.id == fid, (changes, e.id)
        return str(e)
    raise AssertionError("accepted %r" % (changes,))


refused({"nothing.here": 1}, "nothing.here")
refused({"vu.on": "yes"}, "vu.on")
refused({"info.secs": 2}, "info.secs")
refused({"info.secs": True}, "info.secs")
refused({"vu.layout": "round"}, "vu.layout")
refused({"inputs.CD": "Café"}, "inputs.CD")
refused({"inputs.CD": "x" * 17}, "inputs.CD")
refused({"vu.on": True}, "vu.on")                       # the VU needs its source first
assert settings.patch(cfg, {"vu.on": True, "vu.relay": "192.168.178.99"})["vu"]["on"] is True

# --- the routes ----------------------------------------------------------------------------------------
web = types.ModuleType("web")
sys.modules["web"] = web
answers = []


async def reply(writer, status, ctype, body):
    answers.append((status, body))


async def reply_json(writer, obj, status="200 OK"):
    answers.append((status, obj))


web.reply, web.reply_json = reply, reply_json


class Reader:
    def __init__(self, body):
        self.body = body

    async def readexactly(self, n):
        return self.body[:n]


def request(method, path, body=b""):
    return types.SimpleNamespace(method=method, path=path, length=len(body), reader=Reader(body))


saved = []
current = {"cfg": cfg}


def apply(c):
    saved.append(c)
    current["cfg"] = c


routes = settings.Routes(lambda: current["cfg"], apply)
run = asyncio.run
run(routes.handle(request("GET", "/settings"), None))
assert answers[-1] == ("200 OK", flat)
run(routes.handle(request("PATCH", "/settings", b'{"inputs.DVD": "Apple TV"}'), None))
assert answers[-1][0] == "200 OK" and answers[-1][1]["inputs.DVD"] == "Apple TV" and len(saved) == 1
run(routes.handle(request("PATCH", "/settings", b'{"info.secs": 99}'), None))
assert answers[-1][0] == "400 Bad Request" and answers[-1][1]["id"] == "info.secs" and len(saved) == 1
run(routes.handle(request("PATCH", "/settings", b'not json'), None))
assert answers[-1][0] == "400 Bad Request"
run(routes.handle(request("GET", "/names"), None))
assert answers[-1][0] == "404 Not Found", "the contract v1 route is gone"
print("all good")
