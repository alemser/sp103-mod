"""Servidor HTTP do Pico: publica o estado do amp na rede (o Wi-Fi fica no wifi.py).

    GET /state    o estado em JSON
    GET /events   Server-Sent Events: um "data: {json}" quando muda (no máximo 4 por segundo)
    GET /names    os textos personalizados (nomes das entradas e telas de inicialização)
    PUT /names    troca os textos: {"inputs": {"TUNER": "Rega Planar 2"}, "boot": [...], "about": [...],
                  "vu": {"on": true, "layout": "bars", "relay": "192.168.1.50"},
                   "info": {"on": true, "mode": "temp", ...}}      (telas de informação)
                  (texto vazio = original; ver names.py)
    outras        rotas extras, por prefixo: routes={"/update": ota.handle, "/bus": log.handle, "/device": device.handle}

Uso (com asyncio):
    pub = Publisher(state, get_names=g, set_names=s)   # s(cfg) valida, guarda e aplica; levanta ValueError
    (routes: handler(req, writer) assíncrono; req = Request, ver abaixo; responde com reply())
    asyncio.create_task(pub.serve())
    ...
    pub.changed()      # chame depois de cada state.update() que devolveu True
"""

import json
import asyncio

from listeners import make_room

CHUNK = 1024                    # o corpo vai em pedaços: o Wi-Fi do Pico tem pouca memória
# /events: no máximo um estado a cada EVENT_GAP_S, sempre o mais recente. Mandar um a cada mudança
# de tela (girar o volume dá dezenas por segundo) enche a memória do lwIP, e aí cada escrita trava
# o Pico por 10 s (issue #2): o menu do Function fecha antes da tecla chegar.
EVENT_GAP_S = 0.25
PING_S = 1                      # o groove-rig desiste depois de 5 s sem nada


class Request:
    """Um pedido HTTP já lido até os cabeçalhos. O corpo fica em reader (length bytes)."""

    def __init__(self, method, path, headers, reader):
        self.method = method
        self.path, _, query = path.partition("?")
        self.query = {}                 # "?tz=120&x=1" -> {"tz": "120", "x": "1"}
        for p in query.split("&"):
            key, _, value = p.partition("=")
            self.query[key] = value
        self.headers = headers          # nomes em minúsculas
        self.reader = reader
        self.length = int(headers.get("content-length", 0))


async def reply(writer, status, ctype, body):
    # no-store: tudo aqui muda com o estado e com as atualizações por OTA.
    writer.write(("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nCache-Control: no-store\r\n"
                  "Access-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n"
                  % (status, ctype, len(body))).encode())
    await writer.drain()
    # Em pedaços: uma resposta grande de uma vez aperta a memória do Wi-Fi (issue #2).
    for i in range(0, len(body), CHUNK):
        writer.write(body[i:i + CHUNK])
        await writer.drain()


async def reply_json(writer, obj, status="200 OK"):
    await reply(writer, status, "application/json", json.dumps(obj).encode())


class Publisher:
    def __init__(self, state, get_names=None, set_names=None, port=80, routes=None, names_extra=None):
        self.state = state
        self.get_names = get_names
        self.set_names = set_names
        self.names_extra = names_extra  # campos a mais no GET /names (ex.: as contagens do proxy)
        self.port = port
        self.routes = routes or {}
        self.listeners = []             # conexões abertas em /events: (ip, writer), ver listeners.py
        self.served = 0                 # pedidos respondidos desde que o Pico ligou
        self.version = 0                # sobe a cada changed(); cada ouvinte guarda o último que enviou

    def _json(self):
        return json.dumps(self.state.to_dict())

    def changed(self):
        """Marca que o estado mudou (chamar depois de cada mudança). Quem envia é o laço de cada
        ouvinte em _events(), no máximo um estado a cada EVENT_GAP_S, sempre o mais recente."""
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

            if path == "/names":
                await self._names(writer, req.method,
                                  await reader.readexactly(req.length) if req.length else b"")
            elif path == "/state":
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

    async def _names(self, writer, method, body):
        import names
        status, answer = "200 OK", None
        if method == "PUT" and self.set_names:
            try:
                self.set_names(json.loads(body))
            except ValueError as e:     # JSON inválido ou texto recusado por names.validate
                status, answer = "400 Bad Request", {"error": str(e)}
        if answer is None:
            answer = {"config": self.get_names(), "inputs": names.INPUTS,
                      "defaults": {"boot": ["ACOUSTIC", "SOLUTIONS"],
                                   "about": ["Amplifier SP103", "SW version 1.0"]}}
            if self.names_extra:
                answer.update(self.names_extra())
        await reply_json(writer, answer, status)

    async def _events(self, writer):
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                     b"Cache-Control: no-cache\r\nAccess-Control-Allow-Origin: *\r\n\r\n")
        try:
            ip = writer.get_extra_info("peername")[0]
        except Exception:
            ip = None
        make_room(self.listeners, ip)
        writer.write(("data: " + self._json() + "\n\n").encode())   # estado atual logo de cara
        entry = (ip, writer)
        self.listeners.append(entry)
        sent = self.version
        quiet = 0
        try:
            while entry in self.listeners:      # fora da lista = outra conexão tomou o lugar
                await writer.drain()            # falha se a conexão caiu
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
                        writer.write(b": ping\n\n")   # comentário SSE: mantém a conexão viva
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
