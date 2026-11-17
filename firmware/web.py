"""The Pico's HTTP server: publishes the device's state on the network (Wi-Fi is in wifi.py).

This file belongs to the shared base (device-link, firmware-base/): change it there and copy it with copiar.py, never here.

    GET /state    the state as JSON
    GET /events   Server-Sent Events: one "data: {json}" on change (at most 4 per second, always the latest)
    others        extra routes, by prefix: routes={"/update": ota.handle, "/device": device.handle}

Use (with asyncio):
    pub = Publisher(state, routes={...})
    (routes: async handler(req, writer); req = Request, below; answers with reply())
    asyncio.create_task(pub.serve())
    ...
    pub.changed()      # call after every state change
"""

import json
import asyncio

from listeners import make_room

CHUNK = 1024                    # the body goes in chunks: the Pico's Wi-Fi has little memory
# /events: at most one state every EVENT_GAP_S, always the latest. Sending one on every change (turning the SP103's
# volume gives dozens per second) fills lwIP's memory, and then each write stalls the Pico for 10 s (SP103 issue #2).
EVENT_GAP_S = 0.25
PING_S = 1                      # groove-rig gives up after 5 s of silence


class Request:
    """An HTTP request read up to its headers. The body is left in reader (length bytes)."""

    def __init__(self, method, path, headers, reader):
        self.method = method
        self.path, _, query = path.partition("?")
        self.query = {}                 # "?tz=120&x=1" -> {"tz": "120", "x": "1"}
        for p in query.split("&"):
            key, _, value = p.partition("=")
            self.query[key] = value
        self.headers = headers          # names in lower case
        self.reader = reader
        self.length = int(headers.get("content-length", 0))


async def reply(writer, status, ctype, body):
    # no-store: everything here changes with the state and with OTA updates.
    writer.write(("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nCache-Control: no-store\r\n"
                  "Access-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n"
                  % (status, ctype, len(body))).encode())
    await writer.drain()
    # In chunks: a large answer in one go squeezes the Wi-Fi's memory (SP103 issue #2).
    for i in range(0, len(body), CHUNK):
        writer.write(body[i:i + CHUNK])
        await writer.drain()


async def reply_json(writer, obj, status="200 OK"):
    await reply(writer, status, "application/json", json.dumps(obj).encode())


class Publisher:
    def __init__(self, state, port=80, routes=None):
        self.state = state
        self.port = port
        self.routes = routes or {}
        self.listeners = []             # open /events connections: (ip, writer), see listeners.py
        self.served = 0                 # requests answered since the Pico started
        self.version = 0                # goes up on every changed(); each listener keeps the last one it sent

    def _json(self):
        return json.dumps(self.state.to_dict())

    def changed(self):
        """Marks the state as changed (call after each change). Each listener's loop in _events() does the sending, at
        most one state every EVENT_GAP_S, always the latest."""
        self.version += 1

    async def serve(self):
        await asyncio.start_server(self._client, "0.0.0.0", self.port)

    async def _client(self, reader, writer):
        try:
            request = await reader.readline()
            headers = {}
            while True:
                line = await reader.readline()
                if not line or line == b"\r\n":
                    break
                name, _, value = line.decode().partition(":")
                headers[name.strip().lower()] = value.strip()
            parts = request.split()
            req = Request(parts[0].decode() if parts else "GET",
                          parts[1].decode() if len(parts) > 1 else "/", headers, reader)
            path = req.path
            route = path.split("/")[1].split(".")[0]    # "/bus.csv" -> "bus"; "/update/x" -> "update"
            self.served += 1

            if path == "/state":
                await reply(writer, "200 OK", "application/json", self._json().encode())
            elif path == "/events":
                await self._events(writer)
                return
            elif "/" + route in self.routes:
                await self.routes["/" + route](req, writer)
            else:
                await reply(writer, "404 Not Found", "text/plain", b"not found\n")
        except Exception as e:
            print("http:", e)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

    async def _events(self, writer):
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                     b"Cache-Control: no-cache\r\nAccess-Control-Allow-Origin: *\r\n\r\n")
        try:
            ip = writer.get_extra_info("peername")[0]
        except Exception:
            ip = None
        make_room(self.listeners, ip)
        writer.write(("data: " + self._json() + "\n\n").encode())   # the current state straight away
        entry = (ip, writer)
        self.listeners.append(entry)
        sent = self.version
        quiet = 0
        try:
            while entry in self.listeners:      # off the list = another connection took its place
                await writer.drain()            # fails if the connection dropped
                await asyncio.sleep(EVENT_GAP_S)
                if entry not in self.listeners:
                    break
                if self.version != sent:
                    sent = self.version
                    quiet = 0
                    writer.write(("data: " + self._json() + "\n\n").encode())
                else:
                    quiet += 1
                    if quiet * EVENT_GAP_S >= PING_S:
                        quiet = 0
                        writer.write(b": ping\n\n")   # SSE comment: keeps the connection alive
        except Exception:
            pass
        finally:
            if entry in self.listeners:
                self.listeners.remove(entry)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
