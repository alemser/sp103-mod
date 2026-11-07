#!/usr/bin/env python3
"""Testa no computador as telas de informação: firmware/info.py (o pacote "NP"),
firmware/screens.py (quem aparece e o texto) e a configuração (names.py "info").

    python3 tools/test_info.py
"""

import os
import sys
import time as real_time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))

fake_time = types.ModuleType("time")
for k in dir(real_time):
    if not k.startswith("__"):
        setattr(fake_time, k, getattr(real_time, k))
fake_time.ticks_add = lambda a, b: a + b
fake_time.ticks_diff = lambda a, b: a - b
sys.modules["time"] = fake_time

import info      # noqa: E402
import names     # noqa: E402
import screens   # noqa: E402

sys.modules["time"] = real_time
fails = 0


def check(ok, what):
    global fails
    fails += not ok
    print("%-5s %s" % ("ok" if ok else "FALHA", what))


def packet(fields, playing=True):
    flags = 1 if playing else 0
    return b"NP\x01" + bytes([flags]) + "\x1f".join(fields).encode()


def time_a4(elapsed, side_left, artist="Pink Floyd", title="Time", pos="A4", track="4"):
    return [artist, title, pos, str(elapsed), "421", "A", track, "5", str(side_left), "312", "62"]


def cfg(**kw):
    return names.validate({"info": dict({"on": True}, **kw)})["info"]


# --- info.py: o pacote ---------------------------------------------------------
i = info.Info()
i.on = True
i.feed(packet(time_a4(161, 544)), 1000)
check(i.data["artist"] == "Pink Floyd" and i.data["stylus_hours"] == 312 and i.data["stylus_wear"] == 62,
      "lê os campos do pacote")
check(i.playing and i.stream_seq == 0, "tocando; sem streaming")
i.feed(packet(time_a4(161, 544), playing=False, ), 2000)
check(not i.playing, "parou")
i.feed(packet(["x"]), 3000)
check(i.data["stylus_hours"] is None, "campos que faltam no fim: None")
i.feed(packet(time_a4(10, 20)[:9] + ["abc", "62"]), 3500)
check(i.data["stylus_hours"] is None, "número estragado: None")
check(i.fresh(3500 + info.STALE_MS - 1) and not i.fresh(3500 + info.STALE_MS), "sem pacote por 15 s: não vale mais")
check(set(i.status(3500)) == {"on", "packets", "last_packet_ms", "playing", "stream"}, "o estado para o app")


class FakeSock:
    def __init__(self, *a):
        self.sent, self.queue = [], []

    def setblocking(self, f):
        pass

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def recv(self, n):
        if not self.queue:
            raise OSError(11)
        return self.queue.pop(0)

    def close(self):
        pass


info.socket = types.SimpleNamespace(socket=FakeSock, AF_INET=2, SOCK_DGRAM=2)
i = info.Info()
i.configure(True, "192.168.178.99")
check(not i.poll(0) and i.sock.sent == [(b"SUB2\x02", ("192.168.178.99", 7091))], "pede só as telas, à fonte")
i.sock.queue += [b"lixo", "NP\x01\x01Björk".encode("utf-8"), packet(time_a4(1, 2))]
check(i.poll(100) and i.packets == 1, "ignora lixo e pacote fora do ASCII")
i.configure(False, "192.168.178.99")
check(i.sock is None and not i.poll(200) and not i.fresh(200), "desligado: fecha e não pede")

# --- screens.py: textos ---------------------------------------------------------
check(screens.lr("Side A", "track 4/5") == "Side A track 4/5", "esquerda e direita em 16")
check(screens.bar(0.62, 12) == chr(4) * 7 + chr(1) + " " * 4, "barra de 62 % em 12 células")
check(screens.bar(0, 4) == "    " and screens.bar(1.5, 2) == chr(4) * 2, "barra vazia e cheia")
check(screens._last_sunday(2026, 3) == 29 and screens._last_sunday(2026, 10) == 25, "últimos domingos de 2026")
check(screens._last_sunday(2027, 10) == 31, "outubro de 2027: o próprio dia 31")
check(screens.eu_summer((2026, 7, 1, 12)) and not screens.eu_summer((2026, 12, 1, 12)), "verão e inverno")
check(not screens.eu_summer((2026, 3, 29, 0)) and screens.eu_summer((2026, 3, 29, 1)), "muda à 1h UTC em março")
check(screens.eu_summer((2026, 10, 25, 0)) and not screens.eu_summer((2026, 10, 25, 1)), "e em outubro")


def make(**kw):
    i = info.Info()
    i.on = True
    s = screens.Screens(i)
    s.configure(cfg(**kw))
    return i, s


i, s = make(mode="fixed")
check(not s.vu_allowed(), "fixo: o VU não entra")
i.feed(packet(time_a4(161, 544)), 0)
check(s.pick(0, False, True, "PHONO") == "stylus", "fixo: a agulha no toca-discos")
check(s.pick(10000, False, True, "PHONO") == "stylus", "  o tempo todo")
check(s.pick(10000, False, True, "CD") is None, "fixo: noutra entrada, a tela do amp")
check(s.lines("stylus", 0) == ("Stylus     312 h", chr(4) * 7 + chr(1) + "     62%"), "a tela da agulha")
i.feed(packet(time_a4(161, 544)[:9] + ["320", "95"]), 100)
check(s.lines("stylus", 100)[0] == "Replace stylus  ", "agulha gasta: o aviso")
i.feed(packet(time_a4(161, 544)[:9] + ["", ""]), 200)
check(s.pick(200, False, True, "PHONO") is None, "sem os dados da agulha: a tela do amp")
check(s.pick(200, True, False) == "clock", "standby: o relógio")
s.configure(cfg(mode="fixed", clock=False))
check(s.pick(400, True, False) is None, "standby sem o relógio: a tela do amp")
check(s.pick(400 + info.STALE_MS, False, True) == "vu", "sem dados: o VU, se tiver música")

i, s = make(mode="temp", secs=8, turntable=["TUNER"])
check(s.vu_allowed(), "temporário: o VU pode entrar")
playing_a4 = packet(time_a4(0, 900))
stopped = packet(time_a4(0, 900), playing=False)
i.feed(stopped, 0)
check(s.pick(0, False, True, "CD") == "vu", "CD: sem a agulha")
check(s.pick(1000, False, True, "TUNER") == "stylus", "passou para o toca-discos: a agulha")
check(s.pick(8999, False, True, "TUNER") == "stylus" and s.pick(9000, False, True, "TUNER") == "vu",
      "  por 'secs' (8 s), depois o VU")
check(s.pick(20000, False, False, "TUNER") is None, "  sem VU, a tela do amp")
i.feed(playing_a4, 30000)
check(s.pick(30000, False, True, "TUNER") == "stylus", "o disco começou a tocar: a agulha de novo")
i.feed(playing_a4, 35000)
check(s.pick(40000, False, True, "TUNER") == "vu", "o mesmo disco tocando: não volta")
i.feed(packet(time_a4(0, 900, title="Money", pos="B1", track="1")), 45000)
check(s.pick(45000, False, True, "TUNER") == "vu", "faixa nova: não volta")

i, s = make(mode="temp", turntable=["PHONO"])
check(s.pick(0, False, True, "PHONO") == "vu", "sem dados ainda: o VU")
i.feed(stopped, 500)
check(s.pick(500, False, True, "PHONO") == "stylus", "a entrada já era o toca-discos antes do primeiro pacote: conta")
i, s = make(mode="temp", show=["quality"], turntable=["PHONO"])
i.feed(stopped, 0)
check(s.pick(0, False, True, "PHONO") == "vu", "agulha desmarcada: não aparece")
check(cfg(turntable=["TUNER", "PHONO"])["turntable"] == ["PHONO", "TUNER"], "as entradas do toca-discos na ordem do amp")
s.configure(cfg(on=False))
check(s.pick(80000, False, True) == "vu" and s.pick(80000, True, False) is None, "telas desligadas: como antes")

# --- names.py: a configuração ------------------------------------------------------
d = names.validate({})["info"]
check(d == {"on": False, "mode": "temp", "show": ["stylus", "quality"], "secs": 8, "clock": True,
            "utc_offset": 0, "eu_dst": True, "source": "", "turntable": ["PHONO", "TUNER"]},
      "padrão: desligadas")
old = cfg(mode="fixed", fixed="pos", show=["track", "pos", "side", "stylus"], alert=False, scroll=True)
check(old["show"] == ["stylus"] and "fixed" not in old and "alert" not in old and "scroll" not in old,
      "names.json antigo: as telas que saíram e as opções delas são ignoradas")
check(names.INFO_KINDS == screens.KINDS, "names.py e screens.py conhecem as mesmas telas")

# --- streaming: o nome na tela do amp e a tela "quality" ---------------------------
EMPTY11 = [""] * 11                     # nada do groove-identity: o disco não toca
bt_sbc = packet(EMPTY11 + ["bluetooth", "SBC", "44100", "16", "328"], playing=False)
airplay = packet(EMPTY11 + ["airplay", "", "44100", "16", ""], playing=False)
silent = packet(EMPTY11, playing=False)

i, s = make(mode="temp", secs=8)
i.feed(airplay, 0)
check(s.stream_label(0) == "AirPlay", "AirPlay tocando: o nome")
check(names.rewrite("Volume -40.00 dB", "DAB" + " " * 13, names.validate({"inputs": {"DAB": "Streaming"}}), "AirPlay")
      == ("Volume -40.00 dB", "AirPlay         "), "na tela do amp, \"AirPlay\" no lugar de \"Streaming\"")
check(names.rewrite("Volume -40.00 dB", "DAB" + " " * 13, names.validate({"inputs": {"DAB": "Streaming"}}), None)
      == ("Volume -40.00 dB", "Streaming       "), "sem streaming: o nome escolhido")
check(names.rewrite("Volume -40.00 dB", "CD" + " " * 14, names.validate({}), "AirPlay")[1] == "CD" + " " * 14,
      "  só na entrada do streaming (DAB)")
check(s.pick(0, False, False, "DAB") is None, "AirPlay: sem a tela de qualidade (é só do Bluetooth)")

i.feed(bt_sbc, 1000)
check(s.stream_label(1000) == chr(screens.BT) + " Bluetooth", "Bluetooth: o símbolo e o nome")
check(s.pick(1000, False, False, "DAB") == "quality", "o Bluetooth começou: a tela de qualidade")
check(s.lines("quality", 1000) == (chr(screens.BT) + " Bluetooth  SBC", "44.1kHz 16b 328k"), "a tela: %r"
      % (s.lines("quality", 1000),))
check(s.pick(1000 + 7999, False, False, "DAB") == "quality" and s.pick(1000 + 8000, False, False, "DAB") is None,
      "  fica 'secs' (8 s) e sai")
i.feed(bt_sbc, 10000)
check(s.pick(10000, False, False, "DAB") is None, "pacote repetido: não volta")
i.feed(packet(EMPTY11 + ["bluetooth", "AAC", "48000", "16", "256"], playing=False), 12000)
check(s.pick(12000, False, False, "DAB") == "quality" and s.lines("quality", 12000)[1] == "48kHz 16b   256k",
      "a qualidade mudou: a tela volta")
check(s.pick(12000, False, False, "PHONO") is None, "outra entrada: sem a tela de qualidade")
i.feed(silent, 13000)
check(s.stream_label(13000) is None, "o streaming parou: sem nome")
check(s.stream_label(13000 + info.STALE_MS) is None, "sem pacotes: sem nome")

i, s = make(mode="fixed")
i.feed(bt_sbc, 0)
check(s.pick(0, False, False, "DAB") == "quality" and s.pick(10000, False, False, "DAB") == "quality",
      "fixo: a tela de qualidade o tempo todo no Bluetooth")
i, s = make(mode="temp", show=["stylus"])
i.feed(bt_sbc, 0)
check(s.pick(0, False, False, "DAB") is None, "temporário sem a tela marcada: não aparece")
check(screens.GLYPHS[8 * screens.BT:] == screens.BT_GLYPH and screens.GLYPHS[:8 * screens.BT] ==
      screens.vu_meter.GLYPHS[:8 * screens.BT], "o símbolo do Bluetooth no desenho 7; os da barra ficam")
check(cfg(show=["quality", "stylus"])["show"] == ["stylus", "quality"], "as telas marcadas ficam na ordem certa")
check(cfg(utc_offset=5.5)["utc_offset"] == 5.5 and cfg(source=" 192.168.178.99 ")["source"] == "192.168.178.99",
      "fuso com meia hora; IP com espaços")
check(names.validate({"info": {"on": True}})["vu"]["on"] is False, "as telas não mexem no VU")
for bad in ({"mode": "always"}, {"show": ["stylus", "lyrics"]}, {"show": "stylus"},
            {"secs": 2}, {"secs": 8.5}, {"secs": True}, {"utc_offset": 15}, {"utc_offset": 1.1},
            {"source": "oceano.local"}, {"on": "yes"}, {"clock": 1}, {"turntable": ["RADIO"]}, {"turntable": "TUNER"}):
    try:
        names.validate({"info": bad})
        check(False, "recusa %r" % bad)
    except ValueError:
        check(True, "recusa %r" % bad)

# udp.py: com o poll (o MicroPython), o recv() só é chamado com pacote na fila.
import udp   # noqa: E402


class FakePoll:
    def register(self, sock, mask):
        self.sock = sock

    def ipoll(self, timeout):
        return iter([(self.sock, 1)] if self.sock.queue else [])


class CountingSock(FakeSock):
    recvs = 0

    def recv(self, n):
        CountingSock.recvs += 1
        return FakeSock.recv(self, n)


real_select = udp.select
udp.select = types.SimpleNamespace(poll=FakePoll, POLLIN=1)
info.socket = types.SimpleNamespace(socket=CountingSock, AF_INET=2, SOCK_DGRAM=2)
i = info.Info()
i.configure(True, "192.168.178.99")
for t in range(0, 1000, 10):
    i.poll(t)
check(CountingSock.recvs == 0 and isinstance(i._poll, FakePoll), "fila vazia: nem chama o recv (sem erro)")
i.sock.queue.append(packet(time_a4(1, 2)))
check(i.poll(1000) and CountingSock.recvs == 1, "com pacote: lê só ele")
i.configure(False, "192.168.178.99")
check(i._poll is None, "desligado: larga o poll junto com o socket")
udp.select = real_select
check(udp.poller(FakeSock()) is None and udp.ready(None), "socket sem poll: cai no recv com erro, como antes")

print("\ntudo certo" if not fails else "\n%d falha(s)" % fails)
sys.exit(1 if fails else 0)
