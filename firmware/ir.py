"""Sends commands to the amp down the IR line and watches the volume knob.

Wiring (docs/proxy-ligacao.md):

    GP15 = IR receiver output (controller leg 12)
    GP14 = volume encoder E1 (controller leg 22), read only

SAFETY RULE (the same as busy.py's): GP15 is NEVER driven to 1. Its output value stays 0 and only the
direction changes, at the lowest drive strength (2 mA). The line rises through a resistor of about 40 kΩ inside
the receiver (measured 2026-11-06): pulling it to 0 costs about 0.1 mA. GP14 is never an output.

The PIO holds the line at 0 only for a counted time. While waiting for the next time, the line is
released: if the DMA stopped midway, the line would not stay stuck at 0 and the remote keeps working.
The DMA feeds the times by itself, so a pause in Python does not spoil the code being sent.

Create AFTER the Sniffer and the Responder, and as early as possible: until then, GP15 has the
RP2350's pull-down on, and it would load the IR line.
"""

import asyncio
import time
from array import array

import rp2
from machine import Pin, mem32

import ir_codes

IR_PIN, KNOB_PIN = 15, 14
KNOB_POLL_MS = 5
WAKE_WINDOW_MS = 1000           # two E1 changes within this time = someone turned the knob
WAKE_COOLDOWN_MS = 5000         # the command is the same for on and off: never send two in a row
_PADS_BANK0 = 0x40038000
_DRIVE_MASK = 0x3 << 4
_PIO_BASE = (0x50200000, 0x50300000, 0x50400000)
_TXF0 = 0x010                   # input (TX) FIFO of state machine 0; the others follow every 4
_DREQ_PIO_TX0 = (0, 8, 16)      # DMA request "the TX FIFO has room"


@rp2.asm_pio(set_init=rp2.PIO.IN_LOW)
def _pulses():
    # At 1 MHz each jmp loop lasts 1 µs. Each pair of words: line at 0, line released.
    pull()
    mov(x, osr)
    set(pindirs, 1)             # line at 0
    label("mark")
    jmp(x_dec, "mark")
    set(pindirs, 0)             # release the line before waiting for the next word
    pull()
    mov(x, osr)
    label("space")
    jmp(x_dec, "space")


class Remote:
    def __init__(self, sm_id=5):
        # sm_id 5 = PIO1, state machine 1 (state machine 0 is busy.py's).
        self.line = Pin(IR_PIN, Pin.IN, pull=None)
        self.knob = Pin(KNOB_PIN, Pin.IN, pull=None)
        self.sm = rp2.StateMachine(sm_id, _pulses, freq=1_000_000, set_base=Pin(IR_PIN))
        self.sm.exec("set(pins, 0)")
        self.sm.exec("set(pindirs, 0)")
        pad = _PADS_BANK0 + 4 + 4 * IR_PIN
        mem32[pad] = mem32[pad] & ~_DRIVE_MASK & ~1     # 2 mA, slow edge
        self.sm.active(1)
        pio, sm = divmod(sm_id, 4)
        self._fifo = _PIO_BASE[pio] + _TXF0 + 4 * sm
        self.dma = rp2.DMA()
        self._ctrl = self.dma.pack_ctrl(size=2, inc_read=True, inc_write=False,
                                        treq_sel=_DREQ_PIO_TX0[pio] + sm)
        self._words = None              # the DMA reads from here: it must outlive the send
        self._until = time.ticks_ms()
        self.sent = 0
        self.knob_edges = 0
        self._knob_at = time.ticks_add(time.ticks_ms(), -WAKE_WINDOW_MS)
        self._woke_at = time.ticks_add(time.ticks_ms(), -WAKE_COOLDOWN_MS)
        self.wakes = 0
        self.standby = lambda: False    # proxy.py replaces it: only wake when standby is certain

    def sending(self):
        return time.ticks_diff(self._until, time.ticks_ms()) > 0

    def _start(self, words):
        self._words = array("I", words)
        self._until = time.ticks_add(time.ticks_ms(), sum(words) // 1000 + 10)
        self.dma.config(read=self._words, write=self._fifo, count=len(words), ctrl=self._ctrl, trigger=True)
        self.sent += 1

    def send(self, command):
        self._start(ir_codes.frame(command))

    def status(self):
        return {"commands": list(ir_codes.COMMANDS), "sending": self.sending(), "sent": self.sent,
                "line": self.line.value(), "knob": self.knob.value(), "knob_edges": self.knob_edges,
                "wakes": self.wakes}

    def _knob_moved(self):
        """With the amp in standby, turning the knob turns the amp on. In any other state, does nothing."""
        ms = time.ticks_ms()
        turning = time.ticks_diff(ms, self._knob_at) < WAKE_WINDOW_MS
        self._knob_at = ms
        if (turning and self.standby() and not self.sending()
                and time.ticks_diff(ms, self._woke_at) >= WAKE_COOLDOWN_MS):
            self._woke_at = ms
            self.wakes += 1
            self.send("power_toggle")

    async def watch_knob(self):
        """Follows E1. A turn lasts tens of ms, so polling now and then is enough."""
        last = self.knob.value()
        while True:
            now = self.knob.value()
            if now != last:
                last = now
                self.knob_edges += 1
                self._knob_moved()
            await asyncio.sleep_ms(KNOB_POLL_MS)

    async def handle(self, req, writer):
        """/ir routes (see web.Publisher and docs/api-estado.md)."""
        from web import reply, reply_json
        if req.path == "/ir" and req.method == "GET":
            return await reply_json(writer, self.status())
        if req.method != "POST" or req.path != "/ir/send":
            return await reply(writer, "404 Not Found", "text/plain", b"not found\n")
        command = req.query.get("cmd")
        if self.sending():
            return await reply_json(writer, {"error": "busy"}, "400 Bad Request")
        if command not in ir_codes.COMMANDS:
            return await reply_json(writer, {"error": "unknown command"}, "400 Bad Request")
        self.send(command)
        await reply_json(writer, self.status())
