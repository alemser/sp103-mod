"""The Pico's Wi-Fi: the home network, the setup network, and discovery by the app.

This file belongs to the shared base (amp-link, firmware-base/): change it there and copy it with copiar.py, never here.

The home network lives in wifi.json (written by the setup, never by OTA). Without it, secrets.py's WIFI_SSID and
WIFI_PASSWORD apply, for Picos installed before this version.

With no saved network, or unable to connect for OPEN_SETUP_AFTER_S, the Pico opens the setup network
"AmpLink-<PREFIX>-XXXX" (WPA2, key SETUP_KEY, the same on every Pico; the app knows it) and keeps trying the saved
network. Every setup network starts with SETUP_PREFIX: the app asks Android for "a network starting with AmpLink-",
which fits any device. Whoever joins it (the app, or a browser at http://192.168.4.1/) uses the routes below. Once
connected, the setup network closes by itself after CLOSE_SETUP_AFTER_S, time for whoever set it up to read the IP.

    GET    /wifi            {"state", "detail", "ip", "ssid", "setup": {"open", "ssid"}}
                            state and detail: the last attempt (idle, connecting, connected, or failed with the
                            reason); ip: the address on the home network now; ssid: the saved network
    GET    /wifi/networks   [{"ssid", "rssi", "secure"}, ...], strongest first
    PUT    /wifi            {"ssid": "...", "psk": "..."}: switches network (empty psk = open network).
                            Only with the setup network open. If the new one fails, back to the previous one.
    POST   /wifi/setup      opens the setup network for SETUP_WINDOW_S, without leaving the home network
    DELETE /wifi            forgets the saved network (only with the setup network open)
    GET    /                the setup page, only with the setup network open

Discovery: the app broadcasts "AMPLINK?" (or "DEVICELINK?", contract v2) on UDP port DISCOVERY_PORT and the Pico
answers {"name", "model", "ip"}, plus "label" (the full name, to show), "kind" (the type of device) and "api" (the
contract version) when the bridge provides them. So the app finds the Pico without a fixed IP and knows what it found.

Use (with asyncio):
    net = Wifi(model="mr780", hostname="mr780", prefix="MR780",     # each bridge with its own (device.py)
               label="Magnat MR 780", kind="amplifier", api=2)
    asyncio.create_task(net.task(report))     # report(ok, info) once; never raises
    routes={"/wifi": net.handle, "/": net.page, ...}
"""

import json
import time
import network
import asyncio
import socket

import udp

SETUP_KEY = "amplink-setup"
SETUP_PREFIX = "AmpLink-"
PROBES = (b"AMPLINK?", b"DEVICELINK?")  # discovery: api 1 apps ask the first, the DeviceLink app the second
NET_FILE = "wifi.json"
DISCOVERY_PORT = 47800
OPEN_SETUP_AFTER_S = 120    # not connected for this long (with a saved network): open the setup network
CLOSE_SETUP_AFTER_S = 60    # after connecting
SETUP_WINDOW_S = 600        # POST /wifi/setup
CONNECT_TIMEOUT_S = 15
MAX_NETWORKS = 20

# wlan.status() < 0 = failed for good
REASONS = {-1: "connection failed", -2: "network not found", -3: "wrong password"}


def _load(path=NET_FILE):
    """The saved network: {"ssid", "psk"}, or None."""
    try:
        with open(path) as f:
            net = json.load(f)
        if net.get("ssid"):
            return net
    except (OSError, ValueError):
        pass
    try:
        import secrets
        if getattr(secrets, "WIFI_SSID", ""):
            return {"ssid": secrets.WIFI_SSID, "psk": getattr(secrets, "WIFI_PASSWORD", "")}
    except ImportError:
        pass
    return None


def validate(data):
    """The PUT /wifi body. Returns (ssid, psk) or raises ValueError with the message for the app."""
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    ssid = data.get("ssid")
    psk = data.get("psk") or ""
    if not isinstance(ssid, str) or not ssid or len(ssid.encode()) > 32:
        raise ValueError("ssid must have 1 to 32 bytes")
    if not isinstance(psk, str) or (psk and not 8 <= len(psk) <= 63):
        raise ValueError("password must have 8 to 63 characters (or be empty for an open network)")
    return ssid, psk


def collapse(scan, limit=MAX_NETWORKS):
    """WLAN.scan()'s result: one entry per name, the strongest signal, strongest first.
    On rp2 the 6th field is a count, not "hidden": a hidden network just shows an empty name."""
    best = {}
    for ssid, _bssid, _channel, rssi, security, _count in scan:
        if not ssid:
            continue
        name = ssid.decode("utf-8", "replace") if isinstance(ssid, bytes) else ssid
        if name not in best or rssi > best[name]["rssi"]:
            best[name] = {"ssid": name, "rssi": rssi, "secure": security != 0}
    return sorted(best.values(), key=lambda n: -n["rssi"])[:limit]


class Wifi:
    def __init__(self, model, hostname, prefix, net_file=NET_FILE, retry_s=30, quick_tries=3, label="", kind="",
                 api=0):
        self.model = model
        self.label = label              # "Magnat MR 780": for discovery only
        self.kind = kind                # "amplifier", "cd_player"
        self.api = api                  # contract version, in the discovery answer (0 = not sent: api 1 bridges)
        self.hostname = hostname
        self.prefix = prefix
        self.net_file = net_file
        self.retry_s = retry_s
        self.quick_tries = quick_tries
        self.sta = None
        self.ap = None
        self.name = prefix              # "MR780-D85E" once the chip is up: the name in discovery
        self.setup_ssid = SETUP_PREFIX + prefix
        self.status = {"state": "idle", "detail": "", "ip": ""}
        self.pending = None             # (ssid, psk) from PUT /wifi, carried out by task()
        self.close_setup_at = None      # time.time() when the setup network closes
        self.offline_since = None

    # --- the saved network ---

    def saved(self):
        return _load(self.net_file)

    def _save(self, ssid, psk):
        with open(self.net_file, "w") as f:
            json.dump({"ssid": ssid, "psk": psk}, f)

    def _forget(self):
        import os
        try:
            os.remove(self.net_file)
        except OSError:
            pass

    # --- the setup network ---

    def setup_open(self):
        return self.ap is not None and self.ap.active()

    def open_setup(self, window_s=None):
        """Opens the setup network. window_s: it closes by itself after that, even when connected (POST /wifi/setup)."""
        if not self.setup_open():
            self.ap.config(ssid=self.setup_ssid, key=SETUP_KEY)
            self.ap.active(True)
            print("Wi-Fi setup network open: %s, http://%s/" % (self.setup_ssid, self.ap.ifconfig()[0]))
        self.close_setup_at = time.time() + window_s if window_s else None

    def close_setup(self):
        self.close_setup_at = None
        if self.setup_open():
            self.ap.active(False)
            print("Wi-Fi setup network closed")

    # --- connecting ---

    async def _connect(self, ssid, psk, first=False):
        """One attempt. Returns (True, ip) or (False, reason) and updates the status."""
        self.status = {"state": "connecting", "detail": ssid, "ip": ""}
        if not first:
            # Only after the first: with the chip just up, a disconnect() before connect() makes the first attempt
            # fail (status -1).
            self.sta.disconnect()
        if psk:
            self.sta.connect(ssid, psk)
        else:
            self.sta.connect(ssid)
        t0 = time.time()
        while not self.sta.isconnected() and self.sta.status() >= 0 and time.time() - t0 < CONNECT_TIMEOUT_S:
            await asyncio.sleep(0.25)
        if self.sta.isconnected():
            ip = self.sta.ifconfig()[0]
            self.status = {"state": "connected", "detail": ssid, "ip": ip}
            print("Wi-Fi ok: %s, http://%s/device  (or http://%s.local/device)" % (ssid, ip, self.hostname))
            return True, ip
        reason = REASONS.get(self.sta.status(), "timeout")
        self.status = {"state": "failed", "detail": reason, "ip": ""}
        print("Wi-Fi %s: %s" % (ssid, reason))
        return False, reason

    async def _configure(self, ssid, psk):
        """PUT /wifi: tries the new network; if it fails, back to the previous one, and the setup network stays open."""
        previous = self.saved()
        ok, reason = await self._connect(ssid, psk)
        if not ok and reason == REASONS[-1]:
            # "connection failed" (status -1) is sometimes only the first attempt: seen with a phone hotspot on
            # 2026-11-08, as at a chip reset. A wrong password or a missing network don't improve by retrying.
            ok, reason = await self._connect(ssid, psk)
        if ok:
            self._save(ssid, psk)
            self.close_setup_at = time.time() + CLOSE_SETUP_AFTER_S
            return
        failed = self.status
        if previous:
            await self._connect(previous["ssid"], previous["psk"])
        self.status = failed            # whoever set it up needs to see why the new network failed

    async def _wait(self, seconds):
        """Waits, but wakes at once if a PUT /wifi arrives."""
        end = time.time() + seconds
        while self.pending is None and time.time() < end:
            await asyncio.sleep(0.25)

    async def task(self, on_first_result=None):
        """Connects and keeps the Wi-Fi up, in the background. Never raises: without Wi-Fi the rest of the program
        carries on. on_first_result(ok, info) is called once: on connecting, or when the quick attempts run out
        (info = the IP or the reason)."""
        tries = 0
        reported = False
        while True:
            result = None
            try:
                if self.sta is None:
                    network.hostname(self.hostname)
                    self.sta = network.WLAN(network.STA_IF)
                    self.sta.active(True)
                    self.sta.config(pm=0xA11140)    # no power saving: answers faster
                    self.ap = network.WLAN(network.AP_IF)
                    self.ap.active(False)           # may have been left open from before a soft reset
                    mac = self.sta.config("mac")
                    self.name = "%s-%02X%02X" % (self.prefix, mac[-2], mac[-1])
                    self.setup_ssid = SETUP_PREFIX + self.name
                    asyncio.create_task(self._discovery())
                if self.pending:
                    ssid, psk = self.pending
                    self.pending = None
                    await self._configure(ssid, psk)
                    tries = 0
                    if self.sta.isconnected():
                        result = (True, self.status["ip"])
                elif not self.sta.isconnected():
                    net = self.saved()
                    if net is None:
                        self.status = {"state": "idle", "detail": "no network saved", "ip": ""}
                        result = (False, "no network saved")
                    else:
                        tries += 1
                        result = await self._connect(net["ssid"], net["psk"], first=tries == 1)
                elif not reported:
                    # Already connected (program restarted by mpremote, without resetting the Wi-Fi chip).
                    result = (True, self.sta.ifconfig()[0])
                    self.status = {"state": "connected", "detail": "", "ip": result[1]}
                self._supervise()
            except Exception as e:      # Wi-Fi chip trouble etc.
                print("Wi-Fi error:", e)
                result = (False, str(e))
            if self.sta is not None and self.sta.isconnected():
                tries = 0               # if it drops later, start again with quick attempts
            if result and not reported and (result[0] or tries >= self.quick_tries or tries == 0):
                reported = True
                if on_first_result:
                    on_first_result(*result)
            await self._wait(2 if 0 < tries < self.quick_tries else self.retry_s)

    def _supervise(self):
        """Opens the setup network when Wi-Fi is missing, and closes it when no longer needed."""
        now = time.time()
        if self.sta.isconnected():
            self.offline_since = None
            if self.setup_open() and self.close_setup_at is None:
                self.close_setup_at = now + CLOSE_SETUP_AFTER_S   # came back by itself (router restarted)
        else:
            if self.offline_since is None:
                self.offline_since = now
            if not self.setup_open() and (self.saved() is None or now - self.offline_since >= OPEN_SETUP_AFTER_S):
                self.open_setup()
            self.close_setup_at = None   # without Wi-Fi, the setup network stays open
        if self.close_setup_at is not None and now >= self.close_setup_at:
            self.close_setup()

    # --- HTTP ---

    def describe(self):
        """state and detail: the last attempt. ip: the address on the home network now (after a failed switch, the
        previous network's, which the Pico went back to)."""
        net = self.saved()
        ip = self.sta.ifconfig()[0] if self.sta is not None and self.sta.isconnected() else ""
        return {"state": self.status["state"], "detail": self.status["detail"], "ip": ip,
                "ssid": net["ssid"] if net else "",
                "setup": {"open": self.setup_open(), "ssid": self.setup_ssid}}

    async def handle(self, req, writer):
        """Routes /wifi (see web.Publisher)."""
        from web import reply_json
        path, method = req.path.rstrip("/"), req.method
        # The body is always read before answering: closing the connection with unread bytes makes lwIP send a
        # reset, and the client loses the answer (seen with PUT's 403).
        body = await req.reader.readexactly(req.length) if req.length else b""
        if path == "/wifi" and method == "GET":
            return await reply_json(writer, self.describe())
        if path == "/wifi/networks" and method == "GET":
            return await reply_json(writer, collapse(self.sta.scan()) if self.sta else [])
        if path == "/wifi/setup" and method == "POST":
            self.open_setup(SETUP_WINDOW_S)
            return await reply_json(writer, self.describe())
        if path == "/wifi" and method in ("PUT", "POST", "DELETE"):
            if not self.setup_open():
                return await reply_json(writer, {"error": "open the setup network first: POST /wifi/setup"},
                                        "403 Forbidden")
            if method == "DELETE":
                self._forget()
                return await reply_json(writer, self.describe())
            try:
                self.pending = validate(json.loads(body))
            except ValueError as e:
                return await reply_json(writer, {"error": str(e)}, "400 Bad Request")
            return await reply_json(writer, {"state": "connecting", "detail": self.pending[0], "ip": ""},
                                    "202 Accepted")
        return await reply_json(writer, {"error": "not found"}, "404 Not Found")

    async def page(self, req, writer):
        """GET /: the setup page, only with the setup network open (the Pico has no web page otherwise)."""
        from web import reply
        if req.path != "/" or not self.setup_open():
            return await reply(writer, "404 Not Found", "text/plain", b"not found\n")
        await reply(writer, "200 OK", "text/html; charset=utf-8", PAGE.replace("NAME", self.setup_ssid).encode())

    # --- discovery ---

    def answer(self):
        if self.sta is not None and self.sta.isconnected():
            ip = self.sta.ifconfig()[0]
        else:
            ip = self.ap.ifconfig()[0] if self.setup_open() else ""
        answer = {"name": self.name, "model": self.model, "ip": ip}
        if self.label:
            answer["label"] = self.label
        if self.kind:
            answer["kind"] = self.kind
        if self.api:
            answer["api"] = self.api        # contract v2: the app knows the version before asking anything
        return json.dumps(answer)

    async def _discovery(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", DISCOVERY_PORT))
        sock.setblocking(False)
        poll = udp.poller(sock)
        while True:
            try:
                while udp.ready(poll):
                    data, addr = sock.recvfrom(64)
                    if data.strip() in PROBES:
                        sock.sendto(self.answer().encode(), addr)
            except OSError:
                pass                    # empty queue (without poll) or Wi-Fi dropped midway
            await asyncio.sleep(0.1)


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>NAME</title>
<style>body{font:18px sans-serif;margin:16px;max-width:480px}button,input,select{font-size:18px;width:100%;
margin:6px 0;padding:8px;box-sizing:border-box}pre{background:#eee;padding:8px;white-space:pre-wrap}</style></head>
<body><h2>NAME</h2><p>Wi-Fi setup</p>
<button onclick="scan()">Find networks</button><select id="ssid"></select>
<input id="psk" type="password" placeholder="Password (empty for an open network)">
<button onclick="go()">Connect</button><pre id="out"></pre>
<script>
const $=id=>document.getElementById(id),out=$('out');
async function scan(){out.textContent='searching...';
 const r=await (await fetch('/wifi/networks')).json();
 $('ssid').innerHTML=r.map(n=>`<option>${n.ssid.replace(/</g,'&lt;')}</option>`).join('');
 out.textContent=r.length+' networks';}
async function go(){
 const r=await fetch('/wifi',{method:'PUT',body:JSON.stringify({ssid:$('ssid').value,psk:$('psk').value})});
 out.textContent=await r.text(); if(!r.ok)return;
 for(let i=0;i<40;i++){await new Promise(r=>setTimeout(r,1000));
  try{const s=await (await fetch('/wifi')).json();
   out.textContent=s.state+(s.detail?': '+s.detail:'')+(s.ip?'\\nIP: '+s.ip:'');
   if(s.state=='connected'||s.state=='failed')return;}catch(e){out.textContent='no answer: '+e;}}}
</script></body></html>"""
