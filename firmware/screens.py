"""Quem aparece no display, e o texto das telas de informação.

O proxy.py pergunta pick() quando a tela do amp não tem a vez (3 s depois de cada
redesenho do controlador). São duas telas, cada uma na sua entrada:

- "stylus": horas e desgaste da agulha, só nas entradas do toca-discos ("turntable":
  PHONO, TUNER...).
- "quality": a qualidade do Bluetooth (codec, sample rate, bits, bitrate), só na entrada
  do streaming (amp_state.STREAMING_INPUT) com o Bluetooth tocando.

Em ordem:

1. Standby: o relógio, se ligado; senão, a tela do amp (apagada).
2. Modo fixo: a tela marcada da entrada de agora, o tempo todo. O VU não entra.
3. Modo temporário: a tela marcada entra por "secs". A agulha, quando o amp passa para
   uma entrada do toca-discos e quando o disco começa a tocar; a qualidade, quando o
   Bluetooth começa ou a qualidade muda. Depois o VU, se ligado; senão, a tela do amp.
4. Sem dados: o VU (que só aparece com música) ou a tela do amp.

O nome do streaming na tela do amp ("AirPlay", "Bluetooth") é o stream_label(), que o
proxy.py passa ao names.rewrite().

Os textos são em inglês, como os do amp. As barras usam os desenhos do VU (vu.GLYPHS); o
desenho 7 (o clip do VU, que as telas não usam) vira o símbolo do Bluetooth.
"""

import time

import vu as vu_meter
from amp_state import STREAMING_INPUT

KINDS = ("stylus", "quality")
STYLUS_WARN = 90                # % de desgaste: "Replace stylus"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MIN_YEAR = 2025                 # antes disso, o relógio do Pico ainda não foi acertado
BT = 7                          # o código do símbolo do Bluetooth (ᛒ) nos desenhos próprios
BT_GLYPH = bytes((0x04, 0x06, 0x15, 0x0E, 0x0E, 0x15, 0x06, 0x04))
GLYPHS = vu_meter.GLYPHS[:8 * BT] + BT_GLYPH
STREAM_NAMES = {"airplay": "AirPlay", "bluetooth": chr(BT) + " Bluetooth"}


def lr(left, right):
    """Texto à esquerda e à direita numa linha de 16."""
    gap = 16 - len(left) - len(right)
    return (left + " " * max(1, gap) + right)[:16]


def center(text):
    left = (16 - len(text)) // 2
    return (" " * left + text + " " * 16)[:16]


def khz(rate):
    """44100 -> "44.1kHz", 48000 -> "48kHz"."""
    if rate % 1000 == 0:
        return "%dkHz" % (rate // 1000)
    return "%d.%dkHz" % (rate // 1000, rate % 1000 // 100)


def with_bt_glyph(cgram):
    """Os desenhos do controlador com o símbolo do Bluetooth no 7 (para a tela do amp)."""
    return bytes(cgram[:8 * BT]) + BT_GLYPH


def bar(fraction, cells):
    """Barra com os desenhos do VU: 5 colunas de pixels por célula."""
    n = int(max(0, min(1, fraction)) * cells * 5 + 0.5)
    out = []
    for c in range(cells):
        filled = n - 5 * c
        out.append(chr(vu_meter.FULL) if filled >= 5 else chr(filled - 1) if filled > 0 else " ")
    return "".join(out)


def _last_sunday(year, month):
    """Dia do último domingo de um mês de 31 dias (março e outubro)."""
    # Dias desde 1970-01-01 (uma quinta) até o dia 31: o algoritmo "days from civil".
    y = year - (month <= 2)
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + 30
    days = era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy - 719468
    weekday = (days + 3) % 7               # 0 = segunda
    return 31 - (weekday + 1) % 7


def eu_summer(t):
    """Horário de verão europeu: do último domingo de março ao de outubro, à 1h UTC."""
    y, m, d, h = t[0], t[1], t[2], t[3]
    if 3 < m < 10:
        return True
    if m == 3:
        ls = _last_sunday(y, 3)
        return d > ls or (d == ls and h >= 1)
    if m == 10:
        ls = _last_sunday(y, 10)
        return d < ls or (d == ls and h < 1)
    return False


class Screens:
    def __init__(self, info):
        self.info = info
        self.cfg = {"on": False, "mode": "temp", "show": list(KINDS), "secs": 8, "clock": True,
                    "utc_offset": 0, "eu_dst": True, "turntable": []}
        self.seen_stream = 0
        self.quality_at = None          # quando a tela "quality" entrou (modo temporário)
        self.stylus_at = None           # quando a tela "stylus" entrou (modo temporário)
        self.was_playing = False
        self.seen_input = None          # a entrada que _pick() viu por último, com dados
        self.key = None
        self.since = 0
        self.input = None               # a entrada do amp agora ("TUNER"), do amp_state
        self.error = None

    def configure(self, cfg):
        """cfg = names.json "info" (names.py)."""
        self.cfg = cfg
        self.seen_stream = self.info.stream_seq
        self.quality_at = self.stylus_at = None
        self.was_playing = self.info.playing
        self.error = None

    def vu_allowed(self):
        """No modo fixo o VU não entra: o Pico nem pede os quadros."""
        return not (self.cfg["on"] and self.cfg["mode"] == "fixed")

    def _has(self, kind):
        d = self.info.data
        if kind not in self.cfg["show"]:
            return False
        if kind == "stylus":
            return d["stylus_hours"] is not None and self.input in self.cfg["turntable"]
        if kind == "quality":
            return d["stream"] == "bluetooth" and self.input == STREAMING_INPUT \
                and (d["codec"] is not None or d["sample_rate"] is not None)
        return False

    def stream_label(self, now):
        """O nome do streaming tocando ("AirPlay", "ᛒ Bluetooth"), para a linha da entrada
        na tela do amp, ou None. Vale com ou sem as telas ligadas."""
        if not self.info.fresh(now):
            return None
        return STREAM_NAMES.get(self.info.data["stream"])

    def _clock_time(self):
        t = time.time()
        if time.gmtime(t)[0] < MIN_YEAR:
            return None
        t += int(self.cfg["utc_offset"] * 3600)
        if self.cfg["eu_dst"] and eu_summer(time.gmtime(time.time())):
            t += 3600
        return time.gmtime(t)

    def pick(self, now, standby, vu_active, amp_input=None):
        """A tela de agora: "vu", uma das telas de informação, ou None (a tela do amp)."""
        self.input = amp_input
        key = self._pick(now, standby, vu_active)
        if key != self.key:
            self.key, self.since = key, now
        return key

    def _shown(self, at, now):
        return at is not None and time.ticks_diff(now, at) < self.cfg["secs"] * 1000

    def _pick(self, now, standby, vu_active):
        cfg, info = self.cfg, self.info
        if standby:
            return "clock" if cfg["on"] and cfg["clock"] and self._clock_time() else None
        if not cfg["on"] or not info.fresh(now):
            return "vu" if vu_active else None
        quality, stylus = self._has("quality"), self._has("stylus")
        if info.stream_seq != self.seen_stream:
            self.seen_stream = info.stream_seq
            self.quality_at = now if quality else None
        # Só com dados: uma troca de entrada antes do primeiro pacote ainda conta.
        entered = self.input != self.seen_input
        started = info.playing and not self.was_playing
        self.seen_input, self.was_playing = self.input, info.playing
        if stylus and (entered or started):
            self.stylus_at = now
        if cfg["mode"] == "fixed":
            return "quality" if quality else "stylus" if stylus else None
        if quality and self._shown(self.quality_at, now):
            return "quality"
        if stylus and self._shown(self.stylus_at, now):
            return "stylus"
        return "vu" if vu_active else None

    def lines(self, key, now):
        """As duas linhas (16 caracteres cada) de uma tela de informação."""
        d = self.info.data
        if key == "stylus":
            wear = d["stylus_wear"]
            l1 = "Replace stylus" if wear is not None and wear >= STYLUS_WARN \
                else lr("Stylus", "%d h" % d["stylus_hours"])
            l2 = (bar(wear / 100, 12) + "%4s" % ("%d%%" % wear)) if wear is not None else ""   # sem rjust no MicroPython
        elif key == "quality":
            l1 = lr(STREAM_NAMES["bluetooth"], d["codec"] or "")
            fmt = [khz(d["sample_rate"])] if d["sample_rate"] else []
            if d["bit_depth"]:
                fmt.append("%db" % d["bit_depth"])
            l2 = lr(" ".join(fmt), "%dk" % d["bitrate"] if d["bitrate"] else "")
        elif key == "clock":
            t = self._clock_time()
            if t is None:
                return " " * 16, " " * 16
            l1 = center("%02d:%02d" % (t[3], t[4]))
            l2 = center("%s %d %s" % (DAYS[t[6]], t[2], MONTHS[t[1] - 1]))
        else:
            l1 = l2 = ""
        return (l1 + " " * 16)[:16], (l2 + " " * 16)[:16]

    def status(self, now):
        return {"on": self.cfg["on"], "mode": self.cfg["mode"], "showing": self.key, "error": self.error}
