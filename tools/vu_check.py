#!/usr/bin/env python3
"""Asks the VU bridge for frames the way the Pico does and says what arrived.

    python3 tools/vu_check.py IP
"""

import socket
import struct
import sys
import time

PORT = 7091
SUBSCRIBE = b"SUB2\x03"         # VU and screens
SECONDS = 6                     # the bridge sends the screens every 5 s, even without changes


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip())
    host = sys.argv[1]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.2)
    sock.sendto(SUBSCRIBE, (host, PORT))
    frames = screens = 0
    flags = 0
    level = 0.0
    end = time.monotonic() + SECONDS
    while time.monotonic() < end:
        try:
            data = sock.recv(512)
        except TimeoutError:
            continue
        except OSError as e:
            sys.exit("%s: no answer (%s). Is the bridge installed?" % (host, e))
        if len(data) == 12 and data[:3] == b"VU\x01":
            _, _, flags, left, right = struct.unpack("<2sBBff", data)
            level = max(level, left, right)
            frames += 1
        elif data[:3] == b"NP\x01":
            screens += 1
    if not frames:
        sys.exit("%s: no frames in %d s. Check that the bridge and groove-detector are running and that "
                 "the board's firewall lets UDP port %d through." % (host, SECONDS, PORT))
    print("%s: %d frames in %d s, %d screen packets, peak level %.4f" % (host, frames, SECONDS, screens, level))
    print("gate: " + ("not read" if not flags & 2 else "music" if flags & 1 else "no music"))


if __name__ == "__main__":
    main()
