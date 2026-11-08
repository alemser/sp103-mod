"""Wi-Fi do Pico: a rede de casa, a rede de configuração e a descoberta pela app.

A rede de casa fica no wifi.json (gravado pela configuração, nunca pelo OTA). Sem ele, vale a do secrets.py
(WIFI_SSID e WIFI_PASSWORD), para os Picos instalados antes desta versão.

Sem rede salva, ou sem conseguir conectar por OPEN_SETUP_AFTER_S, o Pico abre a rede de configuração
"AmpLink-SP103-XXXX" (WPA2, senha SETUP_KEY, a mesma em todos os Picos; a app conhece) e continua tentando a rede
salva. Toda rede de configuração começa com SETUP_PREFIX: a app pede ao Android "uma rede que começa com AmpLink-" e
serve para qualquer amp.
Quem entra nela (a app, ou o navegador em http://192.168.4.1/) usa as rotas abaixo. Depois de conectar, a rede de
configuração fecha sozinha em CLOSE_SETUP_AFTER_S, tempo para quem configurou ler o IP.

    GET    /wifi            {"state", "detail", "ip", "ssid", "setup": {"open", "ssid"}}
                            state e detail: a última tentativa (idle, connecting, connected, ou failed com o
                            motivo); ip: o endereço de agora na rede de casa; ssid: a rede salva
    GET    /wifi/networks   [{"ssid", "rssi", "secure"}, ...], da mais forte para a mais fraca
    PUT    /wifi            {"ssid": "...", "psk": "..."}: troca a rede (psk vazio = rede aberta).
                            Só com a rede de configuração aberta. Se a nova falhar, volta para a anterior.
    POST   /wifi/setup      abre a rede de configuração por SETUP_WINDOW_S, sem largar a rede de casa
    DELETE /wifi            esquece a rede salva (só com a rede de configuração aberta)
    GET    /                a página de configuração, só com a rede de configuração aberta

Descoberta: a app manda "AMPLINK?" por broadcast UDP na porta DISCOVERY_PORT e o Pico responde
{"name", "model", "ip"}. Assim a app acha o Pico sem IP fixo.

Uso (com asyncio):
    net = Wifi(model="sp103", hostname="sp103", prefix="SP103")
    asyncio.create_task(net.task(aviso))      # aviso(ok, info) uma vez, como antes; nunca levanta erro
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
NET_FILE = "wifi.json"
DISCOVERY_PORT = 47800
OPEN_SETUP_AFTER_S = 120    # sem conectar por esse tempo (e com rede salva), abre a rede de configuração
CLOSE_SETUP_AFTER_S = 60    # depois de conectar
SETUP_WINDOW_S = 600        # POST /wifi/setup
CONNECT_TIMEOUT_S = 15
MAX_NETWORKS = 20

# wlan.status() < 0 = falhou de vez
REASONS = {-1: "connection failed", -2: "network not found", -3: "wrong password"}


def _load(path=NET_FILE):
    """A rede salva: {"ssid", "psk"}, ou None."""
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
    """O corpo do PUT /wifi. Devolve (ssid, psk) ou levanta ValueError com a mensagem para a app."""
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
    """O resultado do WLAN.scan(): uma entrada por nome, a de sinal mais forte, da mais forte para a mais fraca.
    No rp2 o 6º campo é uma contagem, não "oculta": a rede oculta aparece só com o nome vazio."""
    best = {}
    for ssid, _bssid, _channel, rssi, security, _count in scan:
        if not ssid:
            continue
        name = ssid.decode("utf-8", "replace") if isinstance(ssid, bytes) else ssid
        if name not in best or rssi > best[name]["rssi"]:
            best[name] = {"ssid": name, "rssi": rssi, "secure": security != 0}
    return sorted(best.values(), key=lambda n: -n["rssi"])[:limit]


class Wifi:
    def __init__(self, model, hostname, prefix, net_file=NET_FILE, retry_s=30, quick_tries=3):
        self.model = model
        self.hostname = hostname
        self.prefix = prefix
        self.net_file = net_file
        self.retry_s = retry_s
        self.quick_tries = quick_tries
        self.sta = None
        self.ap = None
        self.name = prefix              # "SP103-D85E" quando o chip liga: o nome na descoberta
        self.setup_ssid = SETUP_PREFIX + prefix
        self.status = {"state": "idle", "detail": "", "ip": ""}
        self.pending = None             # (ssid, psk) do PUT /wifi, feito pelo task()
        self.close_setup_at = None      # time.time() em que a rede de configuração fecha
        self.offline_since = None

    # --- a rede salva ---

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

    # --- a rede de configuração ---

    def setup_open(self):
        return self.ap is not None and self.ap.active()

    def open_setup(self, window_s=None):
        """Abre a rede de configuração. window_s: fecha sozinha depois disso, mesmo conectado (POST /wifi/setup)."""
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

    # --- conectar ---

    async def _connect(self, ssid, psk, first=False):
        """Uma tentativa. Devolve (True, ip) ou (False, motivo) e atualiza o status."""
        self.status = {"state": "connecting", "detail": ssid, "ip": ""}
        if not first:
            # Só depois da primeira: com o chip recém-ligado, um disconnect() antes do connect() faz a
            # primeira tentativa falhar (status -1).
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
        """O PUT /wifi: tenta a rede nova; se falhar, volta para a anterior e a rede de configuração fica aberta."""
        previous = self.saved()
        ok, reason = await self._connect(ssid, psk)
        if not ok and reason == REASONS[-1]:
            # "connection failed" (status -1) às vezes é só a primeira tentativa: visto com o hotspot do celular
            # em 2026-11-08, como no reset do chip. Senha errada e rede sumida não melhoram tentando de novo.
            ok, reason = await self._connect(ssid, psk)
        if ok:
            self._save(ssid, psk)
            self.close_setup_at = time.time() + CLOSE_SETUP_AFTER_S
            return
        failed = self.status
        if previous:
            await self._connect(previous["ssid"], previous["psk"])
        self.status = failed            # quem configurou precisa ver por que a rede nova falhou

    async def _wait(self, seconds):
        """Espera, mas acorda na hora se chegar um PUT /wifi."""
        end = time.time() + seconds
        while self.pending is None and time.time() < end:
            await asyncio.sleep(0.25)

    async def task(self, on_first_result=None):
        """Conecta e mantém o Wi-Fi, em segundo plano. Nunca levanta erro: sem Wi-Fi, o resto do programa
        (o display) segue normal. on_first_result(ok, info) é chamado uma vez: ao conectar, ou quando as
        tentativas rápidas acabam (info = IP ou o motivo)."""
        tries = 0
        reported = False
        while True:
            result = None
            try:
                if self.sta is None:
                    network.hostname(self.hostname)
                    self.sta = network.WLAN(network.STA_IF)
                    self.sta.active(True)
                    self.sta.config(pm=0xA11140)    # sem economia de energia: responde mais rápido
                    self.ap = network.WLAN(network.AP_IF)
                    self.ap.active(False)           # pode ter ficado aberta de antes de um soft reset
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
                    # Já conectado (programa reiniciado pelo mpremote, sem reset do chip de Wi-Fi).
                    result = (True, self.sta.ifconfig()[0])
                    self.status = {"state": "connected", "detail": "", "ip": result[1]}
                self._supervise()
            except Exception as e:      # chip de Wi-Fi com problema etc.
                print("Wi-Fi error:", e)
                result = (False, str(e))
            if self.sta is not None and self.sta.isconnected():
                tries = 0               # se cair depois, recomeça com tentativas rápidas
            if result and not reported and (result[0] or tries >= self.quick_tries or tries == 0):
                reported = True
                if on_first_result:
                    on_first_result(*result)
            await self._wait(2 if 0 < tries < self.quick_tries else self.retry_s)

    def _supervise(self):
        """Abre a rede de configuração quando falta Wi-Fi, e fecha quando não precisa mais."""
        now = time.time()
        if self.sta.isconnected():
            self.offline_since = None
            if self.setup_open() and self.close_setup_at is None:
                self.close_setup_at = now + CLOSE_SETUP_AFTER_S   # voltou sozinho (roteador religou)
        else:
            if self.offline_since is None:
                self.offline_since = now
            if not self.setup_open() and (self.saved() is None or now - self.offline_since >= OPEN_SETUP_AFTER_S):
                self.open_setup()
            self.close_setup_at = None   # sem Wi-Fi, a rede de configuração fica aberta
        if self.close_setup_at is not None and now >= self.close_setup_at:
            self.close_setup()

    # --- HTTP ---

    def describe(self):
        """state e detail: a última tentativa. ip: o endereço de agora na rede de casa (depois de uma troca que
        falhou, é o da rede anterior, para onde o Pico voltou)."""
        net = self.saved()
        ip = self.sta.ifconfig()[0] if self.sta is not None and self.sta.isconnected() else ""
        return {"state": self.status["state"], "detail": self.status["detail"], "ip": ip,
                "ssid": net["ssid"] if net else "",
                "setup": {"open": self.setup_open(), "ssid": self.setup_ssid}}

    async def handle(self, req, writer):
        """Rotas /wifi (ver web.Publisher)."""
        from web import reply_json
        path, method = req.path.rstrip("/"), req.method
        # O corpo é lido sempre, antes de responder: fechar a conexão com bytes não lidos faz o lwIP mandar um
        # reset, e o cliente perde a resposta (visto com o 403 do PUT).
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
        """GET /: a página de configuração, só com a rede de configuração aberta (o Pico não tem página web)."""
        from web import reply
        if req.path != "/" or not self.setup_open():
            return await reply(writer, "404 Not Found", "text/plain", b"not found\n")
        await reply(writer, "200 OK", "text/html; charset=utf-8", PAGE.replace("NAME", self.setup_ssid).encode())

    # --- descoberta ---

    def answer(self):
        if self.sta is not None and self.sta.isconnected():
            ip = self.sta.ifconfig()[0]
        else:
            ip = self.ap.ifconfig()[0] if self.setup_open() else ""
        return json.dumps({"name": self.name, "model": self.model, "ip": ip})

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
                    if data.strip() == b"AMPLINK?":
                        sock.sendto(self.answer().encode(), addr)
            except OSError:
                pass                    # fila vazia (sem poll) ou o Wi-Fi caiu no meio
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
