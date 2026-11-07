"""Telas de informação: recebe da fonte o que está tocando (docs/api-telas.md).

O Pico não sabe de onde vêm os dados: só conhece o contrato. Pede a cada 2 s ("SUB2" com
o bit das telas) e recebe um pacote "NP" quando algo muda e a cada 5 s:

    "NP" 0x01 flags  campo 0x1F campo ...     (flags: bit 0 = tocando, bit 1 = o lado acabou)

As telas só usam a agulha, o streaming e o "tocando" (screens.py); os outros campos do
contrato (faixa, lado, tempos) são lidos e ignorados. Campo vazio = None. Leve de
propósito: um split por pacote, nada de JSON.
"""

import socket
import time

import udp

PORT = 7091
SUBSCRIBE = b"SUB2\x02"         # só as telas; o VU pede à parte (vu.py)
SUBSCRIBE_MS = 2000             # a fonte esquece o pedido em 6 s
STALE_MS = 15000                # sem pacote por 15 s: os dados não valem mais
FLAG_PLAYING = 1
FIELDS = ("artist", "title", "position", "elapsed", "duration", "side", "side_track", "side_tracks",
          "side_left", "stylus_hours", "stylus_wear", "stream", "codec", "sample_rate", "bit_depth", "bitrate")
NUMBERS = ("elapsed", "duration", "side_track", "side_tracks", "side_left", "stylus_hours", "stylus_wear",
           "sample_rate", "bit_depth", "bitrate")
STREAM_FIELDS = ("stream", "codec", "sample_rate", "bit_depth", "bitrate")


class Info:
    def __init__(self):
        self.on = False
        self.addr = None
        self.sock = None
        self._poll = None
        self.last_sub = None
        self.last_packet = None
        self.packets = 0
        self.playing = False
        self.data = {name: None for name in FIELDS}
        self.stream_seq = 0             # muda quando o streaming (AirPlay, Bluetooth) ou a qualidade muda

    def configure(self, on, source):
        addr = (source, PORT)
        if addr != self.addr or not on:
            self.close()
        self.on = on
        self.addr = addr
        self.last_sub = None            # pede logo

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
            self._poll = None
        self.last_packet = None

    def poll(self, now):
        """Pede e lê os pacotes (sem esperar). True se chegou um pacote novo."""
        if not self.on:
            return False
        if self.sock is None:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setblocking(False)
            self._poll = udp.poller(self.sock)
        if self.last_sub is None or time.ticks_diff(now, self.last_sub) >= SUBSCRIBE_MS:
            self.last_sub = now
            try:
                self.sock.sendto(SUBSCRIBE, self.addr)
            except OSError:
                pass                    # sem Wi-Fi ainda: tenta de novo em 2 s
        new = False
        while udp.ready(self._poll):
            try:
                packet = self.sock.recv(512)
            except OSError:
                break                   # nada na fila
            if len(packet) >= 4 and packet[:3] == b"NP\x01":
                try:
                    self.feed(packet, now)
                except UnicodeError:
                    continue            # fora do contrato (só ASCII): ignora o pacote
                new = True
        return new

    def feed(self, packet, now):
        flags = packet[3]
        parts = str(packet[4:], "ascii").split("\x1f")
        data = {}
        for i, name in enumerate(FIELDS):
            v = parts[i] if i < len(parts) else ""
            if not v:
                v = None
            elif name in NUMBERS:
                try:
                    v = int(v)
                except ValueError:
                    v = None
            data[name] = v
        if any(data[k] != self.data[k] for k in STREAM_FIELDS):
            self.stream_seq += 1
        self.data = data
        self.playing = bool(flags & FLAG_PLAYING)
        self.last_packet = now
        self.packets += 1

    def fresh(self, now):
        return self.on and self.last_packet is not None and time.ticks_diff(now, self.last_packet) < STALE_MS

    def status(self, now):
        age = None if self.last_packet is None else time.ticks_diff(now, self.last_packet)
        return {"on": self.on, "packets": self.packets, "last_packet_ms": age, "playing": self.playing,
                "stream": self.data["stream"]}
