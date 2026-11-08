#!/usr/bin/env python3
"""Testa no computador o Wi-Fi do Pico (firmware/wifi.py), com um chip de Wi-Fi de mentira.

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
    """Os dois lados do chip: a rede de casa (STA) e a de configuração (AP)."""
    routers = {}                # as redes no ar: ssid -> senha ("" = aberta)

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
    """Um Wifi com o chip já ligado, como o task() deixa na primeira volta."""
    path = os.path.join(tmp, name + ".json")
    if saved:
        with open(path, "w") as f:
            json.dump(saved, f)
    FakeWLAN.routers = routers or {}
    net = wifi.Wifi(model="sp103", hostname="sp103", prefix="SP103", net_file=path)
    net.sta, net.ap = FakeWLAN("sta"), FakeWLAN("ap")
    net.name, net.setup_ssid = "SP103-D85E", "AmpLink-SP103-D85E"
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
        raise AssertionError("aceitou %r" % (bad,))
    except ValueError:
        pass

# --- collapse: um por nome, o mais forte, sem os ocultos; o 6º campo (contagem) não importa ---

assert wifi.collapse(FakeWLAN("sta").scan()) == [{"ssid": "Casa", "rssi": -40, "secure": True},
                                                 {"ssid": "Vizinho", "rssi": -70, "secure": False}]
assert len(wifi.collapse([(b"n%d" % i, b"", 1, -i, 0, 1) for i in range(30)])) == 20

# --- a rede salva: wifi.json primeiro, depois o secrets.py dos Picos antigos ---

net = fresh("vazio")
sys.modules["secrets"] = types.SimpleNamespace(WIFI_SSID="Antiga", WIFI_PASSWORD="senha-antiga")
assert net.saved() == {"ssid": "Antiga", "psk": "senha-antiga"}
net = fresh("salvo", saved={"ssid": "Casa", "psk": "12345678"})
assert net.saved() == {"ssid": "Casa", "psk": "12345678"}
sys.modules["secrets"] = types.SimpleNamespace(WIFI_SSID="")
assert fresh("nada").saved() is None

# --- sem rede salva: a rede de configuração abre na hora ---

net = fresh("primeira-vez")
net._supervise()
assert net.setup_open() and net.ap.cfg == {"ssid": "AmpLink-SP103-D85E", "key": "amplink-setup"}
assert request(net, "GET", "/")[0] == 200
assert "SP103-D85E" in request(net, "GET", "/")[1]
status, body = request(net, "GET", "/wifi")
assert status == 200 and body["setup"] == {"open": True, "ssid": "AmpLink-SP103-D85E"} and body["ssid"] == ""
assert request(net, "GET", "/wifi/networks")[1][0]["ssid"] == "Casa"
assert json.loads(net.answer()) == {"name": "SP103-D85E", "model": "sp103", "ip": "192.168.4.1"}

# --- configurar: PUT /wifi, conecta, salva, e a rede de configuração fecha 60 s depois ---

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
assert net.setup_open()                     # ainda: quem configurou precisa ler o IP
clock.now += wifi.CLOSE_SETUP_AFTER_S
net._supervise()
assert not net.setup_open()
assert request(net, "GET", "/")[0] == 404   # sem a rede de configuração, não há página

# --- conectado, a troca de rede só passa com a rede de configuração aberta ---

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

# --- a rede nova falha: o motivo fica no status e o Pico volta para a anterior ---

net.open_setup(wifi.SETUP_WINDOW_S)
run(net._configure("Casa", "senha-errada"))
assert net.status == {"state": "failed", "detail": "wrong password", "ip": ""}
assert net.sta.isconnected() and net.sta.ssid == "Casa"
assert net.saved() == {"ssid": "Casa", "psk": "12345678"}
run(net._configure("Sumiu", ""))
assert net.status["detail"] == "network not found" and net.sta.isconnected()

# --- a rede salva some (roteador desligado): abre a configuração depois de 2 min; fecha quando ela volta ---

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

# --- esquecer a rede ---

net.open_setup(wifi.SETUP_WINDOW_S)
assert request(net, "DELETE", "/wifi")[1]["ssid"] == ""
assert net.saved() is None
assert request(net, "GET", "/wifi/nada")[0] == 404

print("tudo certo")
