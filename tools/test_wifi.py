#!/usr/bin/env python3
"""Tests the Pico's Wi-Fi (firmware/wifi.py) on the computer, with a fake Wi-Fi chip.

This file belongs to the shared base (amp-link, firmware-base/): change it there and copy it with copiar.py, never here.

    python3 tools/test_wifi.py
"""

import asyncio
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))


class Clock:
    now = 1000.0

    def time(self):
        return self.now


clock = Clock()


class FakeWLAN:
    """The chip's two sides: the home network (STA) and the setup network (AP)."""
    routers = {}                # the networks on the air: ssid -> password ("" = open)

    def __init__(self, kind):
        self.kind = kind
        self._active = False
        self.connected = False
        self._status = 0
        self.cfg = {}

    def active(self, on=None):
        if on is None:
            return self._active
        self._active = on

    def config(self, *args, **kw):
        if args == ("mac",):
            return b"\x2c\xcf\x67\xf2\xd8\x5e"
        self.cfg.update(kw)

    def connect(self, ssid, psk=""):
        if ssid not in self.routers:
            self.connected, self._status = False, -2
        elif self.routers[ssid] != psk:
            self.connected, self._status = False, -3
        else:
            self.connected, self._status = True, 3
            self.ssid = ssid

    def disconnect(self):
        self.connected, self._status = False, 0

    def isconnected(self):
        return self.connected

    def status(self):
        return self._status

    def ifconfig(self):
        return ("192.168.4.1",) if self.kind == "ap" else ("192.168.1.77",)

    def scan(self):
        return [(b"Casa", b"x", 6, -50, 3, 1), (b"Casa", b"y", 11, -40, 3, 2), (b"", b"z", 1, -30, 3, 1),
                (b"Vizinho", b"w", 1, -70, 0, 1)]


fake_network = types.SimpleNamespace(STA_IF="sta", AP_IF="ap", hostname=lambda h: None,
                                     WLAN=lambda kind: FakeWLAN(kind))
real_time = sys.modules["time"]
sys.modules["network"] = fake_network
sys.modules["time"] = clock
import wifi   # noqa: E402
import web    # noqa: E402
sys.modules["time"] = real_time


async def fake_sleep(s):
    clock.now += s
    await asyncio.sleep(0)

wifi.asyncio = types.SimpleNamespace(sleep=fake_sleep, create_task=lambda coro: coro.close())

tmp = tempfile.mkdtemp()


def fresh(name, saved=None, routers=None):
    """A Wifi with the chip already up, as task() leaves it on its first round."""
    path = os.path.join(tmp, name + ".json")
    if saved:
        with open(path, "w") as f:
            json.dump(saved, f)
    FakeWLAN.routers = routers or {}
    net = wifi.Wifi(model="demo", hostname="demo", prefix="DEMO", net_file=path)
    net.sta, net.ap = FakeWLAN("sta"), FakeWLAN("ap")
    net.name, net.setup_ssid = "DEMO-D85E", "AmpLink-DEMO-D85E"
    return net


def run(coro):
    return asyncio.run(coro)


class Writer:
    def __init__(self):
        self.data = b""

    def write(self, b):
        self.data += b if isinstance(b, bytes) else b.encode()

    async def drain(self):
        pass


def request(net, method, path, body=None):
    raw = json.dumps(body).encode() if body is not None else b""

    async def readexactly(n):
        return raw[:n]
    req = types.SimpleNamespace(method=method, path=path, length=len(raw),
                                reader=types.SimpleNamespace(readexactly=readexactly))
    w = Writer()
    run((net.page if path == "/" else net.handle)(req, w))
    head, _, payload = w.data.partition(b"\r\n\r\n")
    status = int(head.split()[1])
    return status, (json.loads(payload) if b"application/json" in head else payload.decode())


# --- validate ---

assert wifi.validate({"ssid": "Casa", "psk": "12345678"}) == ("Casa", "12345678")
assert wifi.validate({"ssid": "Aberta"}) == ("Aberta", "")
for bad in ({"ssid": ""}, {"psk": "12345678"}, {"ssid": "Casa", "psk": "1234567"}, {"ssid": "x" * 33}, [1]):
    try:
        wifi.validate(bad)
        raise AssertionError("accepted %r" % (bad,))
    except ValueError:
        pass

# --- collapse: one per name, the strongest, no hidden ones; the 6th field (a count) doesn't matter ---

assert wifi.collapse(FakeWLAN("sta").scan()) == [{"ssid": "Casa", "rssi": -40, "secure": True},
                                                 {"ssid": "Vizinho", "rssi": -70, "secure": False}]
assert len(wifi.collapse([(b"n%d" % i, b"", 1, -i, 0, 1) for i in range(30)])) == 20

# --- the saved network: wifi.json first, then older Picos' secrets.py ---

net = fresh("vazio")
sys.modules["secrets"] = types.SimpleNamespace(WIFI_SSID="Antiga", WIFI_PASSWORD="senha-antiga")
assert net.saved() == {"ssid": "Antiga", "psk": "senha-antiga"}
net = fresh("salvo", saved={"ssid": "Casa", "psk": "12345678"})
assert net.saved() == {"ssid": "Casa", "psk": "12345678"}
sys.modules["secrets"] = types.SimpleNamespace(WIFI_SSID="")
assert fresh("nada").saved() is None

# --- no saved network: the setup network opens at once ---

net = fresh("primeira-vez")
net._supervise()
assert net.setup_open() and net.ap.cfg == {"ssid": "AmpLink-DEMO-D85E", "key": "amplink-setup"}
assert request(net, "GET", "/")[0] == 200
assert "DEMO-D85E" in request(net, "GET", "/")[1]
status, body = request(net, "GET", "/wifi")
assert status == 200 and body["setup"] == {"open": True, "ssid": "AmpLink-DEMO-D85E"} and body["ssid"] == ""
assert request(net, "GET", "/wifi/networks")[1][0]["ssid"] == "Casa"
assert json.loads(net.answer()) == {"name": "DEMO-D85E", "model": "demo", "ip": "192.168.4.1", "api": 2}
# The full name and the kind only appear when the bridge provides them.
net.label, net.kind = "Demo Player", "cd_player"
assert json.loads(net.answer()) == {"name": "DEMO-D85E", "model": "demo", "ip": "192.168.4.1", "api": 2,
                                    "label": "Demo Player", "kind": "cd_player"}
assert wifi.PROBE == b"DEVICELINK?"
net.label, net.kind = "", ""

# --- setting up: PUT /wifi connects, saves, and the setup network closes 60 s later ---

FakeWLAN.routers = {"Casa": "12345678"}
assert request(net, "PUT", "/wifi", {"ssid": "Casa", "psk": "123"})[0] == 400
status, body = request(net, "PUT", "/wifi", {"ssid": "Casa", "psk": "12345678"})
assert status == 202 and net.pending == ("Casa", "12345678")
ssid, psk = net.pending
net.pending = None
run(net._configure(ssid, psk))
assert net.status == {"state": "connected", "detail": "Casa", "ip": "192.168.1.77"}
assert net.saved() == {"ssid": "Casa", "psk": "12345678"}
assert json.loads(net.answer())["ip"] == "192.168.1.77"
net._supervise()
assert net.setup_open()                     # still: whoever set it up needs to read the IP
clock.now += wifi.CLOSE_SETUP_AFTER_S
net._supervise()
assert not net.setup_open()
assert request(net, "GET", "/")[0] == 404   # without the setup network, no page

# --- connected, a network switch only goes through with the setup network open ---

assert request(net, "PUT", "/wifi", {"ssid": "Outra", "psk": "12345678"})[0] == 403
assert request(net, "DELETE", "/wifi")[0] == 403
status, body = request(net, "POST", "/wifi/setup")
assert status == 200 and body["setup"]["open"] and net.sta.isconnected()
clock.now += wifi.SETUP_WINDOW_S - 1
net._supervise()
assert net.setup_open()
clock.now += 1
net._supervise()
assert not net.setup_open()

# --- the new network fails: the reason stays in the status and the Pico goes back to the previous one ---

net.open_setup(wifi.SETUP_WINDOW_S)
run(net._configure("Casa", "senha-errada"))
assert net.status == {"state": "failed", "detail": "wrong password", "ip": ""}
assert net.sta.isconnected() and net.sta.ssid == "Casa"
assert net.saved() == {"ssid": "Casa", "psk": "12345678"}
run(net._configure("Sumiu", ""))
assert net.status["detail"] == "network not found" and net.sta.isconnected()

# --- the saved network goes away (router off): setup opens after 2 min; closes when it comes back ---

net = fresh("roteador", saved={"ssid": "Casa", "psk": "12345678"}, routers={})
net._supervise()
assert not net.setup_open()
clock.now += wifi.OPEN_SETUP_AFTER_S - 1
net._supervise()
assert not net.setup_open()
clock.now += 1
net._supervise()
assert net.setup_open()
FakeWLAN.routers = {"Casa": "12345678"}
run(net._connect("Casa", "12345678"))
net._supervise()
assert net.setup_open()
clock.now += wifi.CLOSE_SETUP_AFTER_S
net._supervise()
assert not net.setup_open()

# --- forgetting the network ---

net.open_setup(wifi.SETUP_WINDOW_S)
assert request(net, "DELETE", "/wifi")[1]["ssid"] == ""
assert net.saved() is None
assert request(net, "GET", "/wifi/nada")[0] == 404

print("all good")
