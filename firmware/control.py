"""Direct amp adjustments: a single request, and the Pico takes care of the clicks and codes.

    POST /control?target=volume&dir=up       volume, bass, treble or balance; dir = up or down
    POST /control?target=loudness&on=1       loudness or speakers; on = 1 or 0
    POST /control?target=key&name=select_cd  one remote key (ir_codes.COMMANDS)

The path in the amp (docs/api-estado.md):
- bass and treble have their own IR key; balance, loudness and speakers only through the Function button
  (panel.py), which steps through the menu: Bass, Treble, Balance, Loudness, Speakers, normal screen;
- inside a menu, volume + and − adjust that menu. Outside it, they adjust the volume;
- the first volume press only opens the screen, so each adjustment checks the value and repeats once;
- a Function click sometimes also selects PHONO: _goto() notices and goes back to the previous input.

Runs the same in MicroPython (Pico) and in the computer's Python (tools/test_control.py).
"""

import asyncio

import ir_codes

MENUS = ("bass", "treble", "balance", "loudness", "speakers")
STEPPED = ("volume", "bass", "treble", "balance")
SWITCHES = ("loudness", "speakers")
KEYS = {"up": "volume_up", "down": "volume_down"}
POLL_MS = 20
SCREEN_MS = 900                 # the amp redraws the screen well before this
SETTLE_MS = 300                 # the same as the groove-rig profile
MENU_END_MS = 7500              # a menu closes by itself in about 6 s
MAX_PRESSES = 12                # two laps around the menu


async def _until(ready, ms):
    for _ in range(ms // POLL_MS):
        if ready():
            return True
        await asyncio.sleep_ms(POLL_MS)
    return ready()


class Control:
    def __init__(self, state, remote, panel):
        self.state = state
        self.remote = remote
        self.panel = panel
        self.busy = False

    def _value(self, target):
        st = self.state
        if target == "volume":
            return st.volume_db
        if target == "bass":
            return st.bass_db
        if target == "treble":
            return st.treble_db
        if target == "balance":
            return st.balance
        return st.loudness if target == "loudness" else st.speakers

    async def _ir(self, command):
        await _until(lambda: not self.remote.sending(), SCREEN_MS)
        self.remote.send(command)

    async def _goto(self, target):
        """Clicks Function until the menu opens. If the amp jumps to another input, restores the previous one."""
        st = self.state
        wanted = st.input_id
        for _ in range(MAX_PRESSES):
            if st.screen == target:
                await asyncio.sleep_ms(SETTLE_MS)
                return
            before = st.screen
            self.panel.press()
            await _until(lambda: st.screen != before or st.input_id != wanted, SCREEN_MS)
            if wanted and st.input_id != wanted:
                await self._ir("select_" + wanted)
                await _until(lambda: st.input_id == wanted, SCREEN_MS)
        raise ValueError("The amp didn't open " + target)

    async def _open(self, target):
        st = self.state
        if target == "volume":
            if not await _until(lambda: st.screen not in MENUS, MENU_END_MS):
                raise ValueError("The amp is still in a menu")
        elif target == "balance":
            await self._goto(target)
        elif st.screen != target:
            await self._ir(target)
            await _until(lambda: st.screen == target, SCREEN_MS)
            await asyncio.sleep_ms(SETTLE_MS)

    async def adjust(self, target, direction):
        await self._open(target)
        old = self._value(target)
        for _ in range(2):
            await self._ir(KEYS[direction])
            if await _until(lambda: self._value(target) != old, SCREEN_MS):
                return

    async def switch(self, target, on):
        await self._goto(target)
        if self._value(target) != on:
            await self._ir(KEYS["up" if on else "down"])
            if not await _until(lambda: self._value(target) == on, SCREEN_MS):
                raise ValueError("The amp didn't change " + target)

    async def run(self, query):
        """Carries out the request. Raises ValueError, with the text to show, if it can't."""
        target = query.get("target")
        if self.busy:
            raise ValueError("Still working on the last change")
        if target == "key":             # also works in standby: that is how the amp turns on
            if query.get("name") not in ir_codes.COMMANDS:
                raise ValueError("Unknown key")
            return await self._ir(query["name"])
        if self.state.power != "on":
            raise ValueError("The amp isn't on")
        if target in STEPPED and query.get("dir") in KEYS:
            work = self.adjust(target, query["dir"])
        elif target in SWITCHES and query.get("on") in ("0", "1"):
            work = self.switch(target, query["on"] == "1")
        else:
            raise ValueError("Unknown control")
        self.busy = True
        try:
            await work
        finally:
            self.busy = False

    async def handle(self, req, writer):
        """/control route (see web.Publisher)."""
        from web import reply, reply_json
        if req.path != "/control" or req.method != "POST":
            return await reply(writer, "404 Not Found", "text/plain", b"not found\n")
        try:
            await self.run(req.query)
        except ValueError as e:
            return await reply_json(writer, {"error": str(e)}, "400 Bad Request")
        await reply_json(writer, self.state.to_dict())
