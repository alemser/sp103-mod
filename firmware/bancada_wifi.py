"""Bench, stage 3: the amp's state on the network, with a "fake amp".

A simulated amp draws the SP103 screens on the spare display, as the controller
would. Each screen goes through the reader (amp_state), exactly as it will
with the sniffer, and the state is published at http://sp103.local/ (or by IP).

Run from the computer:  .venv/bin/mpremote run firmware/bancada_wifi.py
Or standalone, when the Pico powers up: main.py imports this file (see main.py).
"""

import time
import random
import asyncio

import names
import sp103_screens as s
from amp_state import AmpState, INPUTS
from lcd1602 import Lcd1602
import settings
from web import Publisher
from wifi import Wifi

lcd = Lcd1602()
texts = names.load()                    # custom texts (names.py)
state = AmpState(texts["inputs"])
last_screen = ("", "")
net = Wifi(model="sp103", hostname="sp103", prefix="SP103")
pub = None
notice_until = None                     # while a notice is on the display, the screens wait


def draw(l1, l2):
    """Draws the amp's screen on the display, with the names from the table already applied."""
    if notice_until is not None:
        return                          # notice on screen: notice() redraws when it ends
    lcd.reset()                         # recovers the display from a bad contact (see lcd1602.py)
    for code, rows in enumerate(s.CGRAM):
        lcd.define_char(code, rows)
    lcd.show(*names.rewrite(l1, l2, texts))


def show(screen):
    """The "amp" drew a screen: the reader reads the original and the display shows the rewritten one,
    as it will be on the real amp."""
    global last_screen
    last_screen = screen
    if state.update(screen[0], screen[1], time.ticks_ms()):
        pub.changed()
    draw(*screen)


def set_texts(cfg):
    """Called by PATCH /settings (settings.py): validates, saves to flash and applies right away."""
    global texts
    texts = names.validate(cfg)
    names.save(texts)
    if state.set_names(texts["inputs"], time.ticks_ms()):
        pub.changed()
    draw(*last_screen)


class FakeAmp:
    """Imitates the controller: keeps values and draws the same screens it does."""

    def __init__(self):
        self.volume = -28.75
        self.input = "PHONO"
        self.bass = 2
        self.treble = 0
        self.balance = (None, 0.0)
        self.loudness = False
        self.speakers = True

    async def power_on(self):
        show(s.boot())
        await asyncio.sleep(2)
        show(s.about())
        await asyncio.sleep(2)
        show(s.normal(self.volume, self.input))

    async def turn_volume(self, clicks):
        step = 1.25 if clicks > 0 else -1.25
        for _ in range(abs(clicks)):
            self.volume = min(0.0, max(-78.75, self.volume + step))
            show(s.volume_bar(self.volume))
            await asyncio.sleep(0.4)
        await asyncio.sleep(2)          # the bar goes back to the input name by itself
        show(s.normal(self.volume, self.input))

    async def select_input(self, name):
        self.input = name
        show(s.normal(self.volume, self.input))

    async def function_menu(self):
        """The 5 Function menus, changing some value, then back to the normal screen."""
        self.bass = random.choice((-4, -2, 0, 2, 4, 6))
        self.treble = random.choice((-2, 0, 2))
        side = random.choice(("L", "R", None))
        self.balance = (side, 0.0) if side is None else (side, -1.25 * random.randint(1, 10))
        self.loudness = not self.loudness
        for screen in (s.tone("Bass", self.bass), s.tone("Treble", self.treble),
                       s.balance(*self.balance), s.choice("Loudness", self.loudness),
                       s.choice("Speakers", self.speakers)):
            show(screen)
            await asyncio.sleep(1.5)
        show(s.normal(self.volume, self.input))


async def demo():
    amp = FakeAmp()
    await amp.power_on()
    while True:
        await asyncio.sleep(4)
        await amp.turn_volume(random.choice((-4, -2, 2, 4)))
        await asyncio.sleep(4)
        await amp.select_input(random.choice(INPUTS))
        await asyncio.sleep(4)
        await amp.function_menu()
        await asyncio.sleep(4)
        await amp.power_on()            # repeats the boot screens, to show the custom texts


async def notice(line1, line2, seconds=3):
    """Shows a notice for a few seconds, then goes back to the amp's screen."""
    global notice_until
    notice_until = True
    lcd.reset()
    lcd.show(line1, line2)
    await asyncio.sleep(seconds)
    notice_until = None
    draw(*last_screen)


def wifi_result(ok, info):
    # Only shows a notice if the first attempt fails; after that everything carries on, without network.
    if not ok:
        asyncio.create_task(notice("Wi-Fi failed", "offline mode"))


async def main():
    global pub
    config = settings.Routes(lambda: texts, set_texts).handle
    pub = Publisher(state, routes={"/settings": config, "/wifi": net.handle, "/": net.page})
    asyncio.create_task(net.task(wifi_result))
    await asyncio.sleep(0.1)            # Wi-Fi starts before the server opens the socket
    await pub.serve()                   # serves as soon as there is a network
    await demo()                        # the display starts right away, with or without Wi-Fi


asyncio.run(main())
