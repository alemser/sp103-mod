"""Who may stay on /events: one connection per IP, and few in total.

A dead connection (a phone that lost Wi-Fi) only goes away after minutes, and each one holds
lwIP memory and receives writes. With 4 dead at once the server stopped for good
(issue #2). A client that reconnects comes from the same IP: the new connection takes the old one's place.
The cap only acts with too many clients, and then the oldest goes.

Runs the same in MicroPython (Pico) and in the computer's Python (tools/test_listeners.py).
"""

MAX_LISTENERS = 3


def make_room(listeners, ip, limit=MAX_LISTENERS):
    """Makes room for a new connection from ip. listeners: [(ip, writer)], oldest first.
    Whoever leaves the list notices by itself and closes (web.py): nothing writes to it any more."""
    for entry in [e for e in listeners if ip is not None and e[0] == ip]:
        listeners.remove(entry)
    while len(listeners) >= limit:
        listeners.pop(0)
