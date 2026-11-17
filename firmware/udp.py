"""Read a UDP socket without waiting, and without an error when the queue is empty (vu.py, info.py).

This file belongs to the shared base (amp-link, firmware-base/): change it there and copy it with copiar.py, never here.

A bridge's main loop may ask for packets about 1000 times a second. On a non-blocking socket, recv() with an empty
queue raises OSError: each error is a new object in memory, and the garbage makes the collector run more often (each
collection stops the loop for a few ms). With poll, recv() is only called when there is a packet.

    p = poller(sock)            # once, when the socket is opened
    while ready(p):
        data = sock.recv(...)   # still inside a try (Wi-Fi may drop midway)
"""

try:
    import select
except ImportError:
    select = None


def poller(sock):
    """The socket's poll, or None when there is none: the tests' fake socket, or the computer's Python, which has no
    ipoll."""
    try:
        p = select.poll()
        p.register(sock, select.POLLIN)
    except Exception:
        return None
    return p if hasattr(p, "ipoll") else None


def ready(p):
    """Is there a packet waiting? Without poll, always yes (recv() decides, with an error)."""
    if p is None:
        return True
    for _ in p.ipoll(0):            # ipoll: MicroPython doesn't build a list on every call
        return True
    return False
