"""Info screens: receives what is playing from the source (docs/api-telas.md).

The Pico doesn't know where the data comes from: it only knows the contract. It subscribes every 2 s ("SUB2" with
the screens bit) and receives an "NP" packet when something changes and every 5 s:

    "NP" 0x01 flags  field 0x1F field ...     (flags: bit 0 = playing, bit 1 = the side has ended)

The screens only use the stylus, the streaming and "playing" (screens.py); the contract's other
fields (track, side, times) are read and ignored. Empty field = None. Light on
purpose: one split per packet, no JSON.
"""

import socket
import time

import udp

PORT = 7091
SUBSCRIBE = b"SUB2\x02"         # only the screens; the VU subscribes separately (vu.py)
SUBSCRIBE_MS = 2000             # the source forgets the subscription after 6 s
STALE_MS = 15000                # no packet for 15 s: the data is no longer valid
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
        self.stream_seq = 0             # changes when the streaming (AirPlay, Bluetooth) or the quality changes

    def configure(self, on, source):
        addr = (source, PORT)
        if addr != self.addr or not on:
            self.close()
        self.on = on
        self.addr = addr
        self.last_sub = None            # subscribe right away

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
            self._poll = None
        self.last_packet = None

    def poll(self, now):
        """Subscribes and reads the packets (without waiting). True if a new packet arrived."""
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
                pass                    # no Wi-Fi yet: tries again in 2 s
        new = False
        while udp.ready(self._poll):
            try:
                packet = self.sock.recv(512)
            except OSError:
                break                   # nothing in the queue
            if len(packet) >= 4 and packet[:3] == b"NP\x01":
                try:
                    self.feed(packet, now)
                except UnicodeError:
                    continue            # outside the contract (ASCII only): ignore the packet
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
