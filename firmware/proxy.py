"""Stage 6: the Pico in the middle, between the amp's controller and the display (option 3b).

The amp's display was desoldered at pins 4..14 (docs/proxy-ligacao.md):
- controller side: GP2..GP12 (E, RS, RW, D0..D7), as in the listener. The Pico only reads
  (sniffer.py) and answers "free" to busy-flag reads (busy.py), pulling D7 to 0;
- display side: GP16..21 (RS, E, D4..D7), 4-bit mode, display RW tied to GND (lcd1602.py).

Each complete controller screen is rebuilt (hd44780.py), goes to the reader (amp_state)
and is drawn on the amp's display with the custom texts already applied (names.rewrite).
The custom characters (CGRAM) and "display on/off" follow the controller's.

With the VU enabled in the settings (vu.py), the two lines become the L and R bars while
music is playing; each controller redraw brings the amp screen back for 3 s. With the info
screens enabled (info.py receives, screens.py chooses), the display also shows the stylus
(on the turntable) and the Bluetooth quality (on DAB). The standby clock was removed on 2026-11-16.

Publishes the state on the network (web.py; the client is the app in the amp-link
repository), with /bus and updates over Wi-Fi, like the listener. Without Wi-Fi, the
display keeps working.

Commands the amp over the IR line, turns the amp on when someone turns the volume knob in
standby (ir.py) and presses the Function button from inside (panel.py). The direct
settings are in control.py.

Run from the computer:  .venv/bin/mpremote run firmware/proxy.py
Or on its own, when the Pico powers up: main.py imports escuta.py, which imports this file.
"""

# First of all: the controller sits still, asking "busy?", until the Pico answers.
# The Sniffer comes before the Responder (see busy.py).
from sniffer import Sniffer
sniffer = Sniffer()
import busy
responder = busy.Responder()
# Right after: remove the pull-down on GP15, which would load the IR line (ir.py).
import ir
remote = ir.Remote()
import panel
front_panel = panel.Panel()

import time
import asyncio

import info as info_feed
import names
import device
import ota
import screens as screens_mod
import sp103_screens as s
import vu as vu_meter
from amp_state import AmpState
from buslog import BusLog
from control import Control
from hd44780 import Bus, RW
from lcd1602 import Lcd1602
from web import Publisher
from wifi import Wifi

# A screen is complete when the controller goes this long without writing
# (it redraws both lines in about 8.5 ms, with one write every ~115 µs).
QUIET_US = 2000
REFRESH_MS = 30_000                     # redraw everything now and then (noise on the wires)
AMP_HOLD_MS = 3000                      # with the VU on, the amp screen stays 3 s after each redraw
PICK_MS = 100                           # choose the screen at most every 100 ms (or on each frame/packet)
OWN_REDRAW_MS = 250                     # an info screen is recomputed every 250 ms (scrolling)
CLOCK_EVERY_S = 6 * 3600                # set the clock from the internet every 6 h
D7 = 1 << 10                            # D7 in the sniffer word (hd44780.py)

lcd = Lcd1602()                         # already clears the display
texts = names.load()                    # custom texts (names.py)
state = AmpState(texts["inputs"])
remote.standby = lambda: state.power == "standby"
control = Control(state, remote, front_panel)
bus = Bus()
# The Pico may power up after the controller has written the characters (when the amp
# powers on): start with the ones from the captures; the model swaps them if the
# controller writes others.
bus.lcd.cgram[:] = bytes(b for rows in s.CGRAM for b in rows)
log = BusLog(bus)
net = Wifi(model="sp103", hostname="sp103", prefix="SP103")   # home network, setup and discovery
pub = None
wifi_ok = False
listen_ticks = 0                        # listener loop count: shows it has not hung
busy_high = 0                           # reads in which the controller saw "busy"
answered = False                        # there has been a read with "free" (the Responder is up)
shown = [None, None]                    # what is on the amp's display now
shown_cgram = None
shown_on = None
last_full = time.ticks_ms()
vu = vu_meter.Vu()
info = info_feed.Info()
screens = screens_mod.Screens(info)
own = None                              # our own screen on the display ("vu", "stylus"...); None = the amp's
own_at = time.ticks_ms()                # when it was drawn
amp_until = time.ticks_ms()             # until then, the amp screen has the turn


def configure_feeds(cfg):
    """Apply the VU and screen settings. In fixed mode the VU does not even request frames.
    Source packets come whenever there is a source, even with the screens off: they provide
    the streaming name on the amp screen ("AirPlay" in place of the DAB input name)."""
    screens.configure(cfg["info"])
    vu_cfg = dict(cfg["vu"])
    vu_cfg["on"] = vu_cfg["on"] and screens.vu_allowed()
    vu.configure(vu_cfg)
    source = cfg["info"]["source"] or cfg["vu"]["relay"]
    info.configure(bool(source), source)


configure_feeds(texts)


def draw(full=False):
    """Put the controller's screen on the amp's display, with the custom texts and the name
    of the stream playing. Sends only what changed; full=True resyncs and rewrites
    everything (without clearing the screen)."""
    global shown_cgram, shown_on, last_full, own
    own = None
    m = bus.lcd
    if full:
        lcd.resync()
        shown[0] = shown[1] = shown_cgram = shown_on = None
        last_full = time.ticks_ms()
    line1, line2 = m.lines()
    label = screens.stream_label(time.ticks_ms())
    lines = names.rewrite(line1, line2, texts, label)
    # "ᛒ Bluetooth" uses character 7, which the controller's screens do not use (only 0, the box).
    bt = label == screens_mod.STREAM_NAMES["bluetooth"] and lines[1].startswith(label)
    cgram = screens_mod.with_bt_glyph(m.cgram) if bt else bytes(m.cgram)
    if cgram != shown_cgram:
        for code in range(8):
            lcd.define_char(code, cgram[8 * code:8 * code + 8])
        shown_cgram = cgram
    for row, text in enumerate(lines):
        if text != shown[row]:
            lcd.write_line(row, text, shown[row])
            shown[row] = text
    if m.display_on != shown_on:
        lcd.display(m.display_on)
        shown_on = m.display_on


def show_own(key, ms, full=False):
    """Put one of our own screens on the display: the VU or an info screen. Its characters
    replace the controller's; the next draw() writes the controller's back (shown_cgram
    changes). Sends only the lines that changed."""
    global shown_cgram, last_full, own, own_at
    own, own_at = key, ms
    if full:
        lcd.resync()
        shown[0] = shown[1] = shown_cgram = None
        last_full = time.ticks_ms()
    glyphs = vu.glyphs if key == "vu" else screens_mod.GLYPHS
    if shown_cgram != glyphs:
        for code in range(8):
            lcd.define_char(code, glyphs[8 * code:8 * code + 8])
        shown_cgram = glyphs
    lines = vu.lines() if key == "vu" else screens.lines(key, ms)
    for row, text in enumerate(lines):
        if text != shown[row]:
            lcd.write_line(row, text, shown[row])
            shown[row] = text


def set_texts(cfg):
    """Called by PUT /names: validates, saves to flash and applies at once."""
    global texts
    texts = names.validate(cfg)
    names.save(texts)
    if state.set_names(texts["inputs"], time.ticks_ms()):
        pub.changed()
    configure_feeds(texts)
    draw()


def status():
    ms = time.ticks_ms()
    return {"proxy": {"reads": bus.reads, "writes": bus.writes, "busy_high": busy_high},
            "vu": vu.status(ms), "info": info.status(ms), "screens": screens.status(ms)}


async def listen():
    global listen_ticks, busy_high, answered, amp_until
    quiet_since = time.ticks_us()
    picked_at = time.ticks_ms()
    key = None
    clears = 0
    clears_seen = 0                     # bus.clears at the previous screen
    while True:
        n = 0
        ms = time.ticks_ms()
        for word in sniffer.read():
            if word & RW:
                # Before the first "free", "busy" is just the Pico still starting up (the sniffer
                # starts a few ms before the Responder). After that it is a Responder failure: it should stay at 0.
                if not word & D7:
                    answered = True
                elif answered:
                    busy_high += 1
            bus.feed(word)
            log.add(ms, word)
            n += 1
        log.poll(ms, n)
        listen_ticks += 1
        if bus.clears != clears:
            clears = bus.clears
            print("amp: power on (display reset)")
        now = time.ticks_us()
        if n:
            quiet_since = now
        quiet = time.ticks_diff(now, quiet_since) > QUIET_US
        if not n and bus.pending and quiet:
            screen = bus.take()
            amp_until = time.ticks_add(ms, AMP_HOLD_MS)
            draw()
            cleared, clears_seen = bus.clears != clears_seen, bus.clears
            if state.update(screen[0], screen[1], time.ticks_ms(), cleared):
                pub.changed()           # no print here: turning the volume gives several per second
            log.screen(ms, state.screen != "unknown")
        elif not n and quiet and time.ticks_diff(ms, last_full) > REFRESH_MS:
            if own:
                show_own(own, ms, full=True)
            else:
                draw(full=True)
        # Our own screens (VU and info): only with the display on and the amp screen not
        # having the turn. Choosing is cheap, but runs at most every PICK_MS, or when a VU
        # frame or a screens packet arrives. An error here turns off the VU and the screens
        # and keeps the amp display: with them saved as on, an error that crashed the program
        # would make the Pico reboot endlessly.
        try:
            new_frame = vu.poll(ms)
            new_info = info.poll(ms)
            if time.ticks_diff(ms, amp_until) < 0 or not bus.lcd.display_on:
                key = None                  # the amp screen has the turn (checked on every loop)
                picked_at = time.ticks_add(ms, -PICK_MS)   # choose as soon as it ends
            elif new_frame or new_info or time.ticks_diff(ms, picked_at) >= PICK_MS:
                picked_at = ms
                key = screens.pick(ms, state.power == "standby", vu.active(ms), state.input)
            if key and not bus.pending:
                if key == "vu":
                    if new_frame or own != "vu":
                        show_own("vu", ms)
                elif key != own or new_info or time.ticks_diff(ms, own_at) >= OWN_REDRAW_MS:
                    show_own(key, ms)
            elif own and not key:
                draw()
            elif new_info and not own and not bus.pending:
                draw()                  # streaming started or stopped: the input name changes
        except Exception as e:
            print("screens: turned off after an error:", repr(e))
            vu.error = screens.error = repr(e)
            vu.on = False
            vu.close()
            info.configure(False, "0.0.0.0")
            off = dict(screens.cfg)
            off["on"] = False
            screens.cfg = off
            key = None
            draw(full=True)
        await asyncio.sleep_ms(1)


def wifi_result(ok, info):
    global wifi_ok
    wifi_ok = ok
    if not ok:
        print("Wi-Fi failed: offline mode")     # the amp display shows no warnings
    else:
        asyncio.create_task(clock_task())


async def clock_task():
    """Set the clock from the internet (NTP), so the bus log has timestamps."""
    import ntptime
    while True:
        try:
            ntptime.settime()                   # the Pico's clock runs in UTC
            # time.time() has only seconds: wait for the second to tick over to match ticks_ms.
            t0 = time.time()
            while time.time() == t0:
                await asyncio.sleep_ms(5)
            log.set_clock(time.time(), time.ticks_ms())
            print("clock set (UTC):", time.gmtime()[:6])
            await asyncio.sleep(CLOCK_EVERY_S)
        except Exception as e:                  # no internet: try again in 1 min
            print("clock:", e)
            await asyncio.sleep(60)


async def confirm_update():
    """New version on trial (ota.py): confirm it once it proves healthy. Without this,
    main.py rolls back to the previous version. Healthy = the listener runs, Wi-Fi has
    connected and the server has answered someone (tools/enviar.py polls every 2 s), for
    20 s in a row."""
    if not ota.in_trial():
        return
    start = time.ticks_ms()
    seen = listen_ticks
    while True:
        await asyncio.sleep(2)
        alive = listen_ticks != seen
        seen = listen_ticks
        if not (alive and wifi_ok and pub.served):
            start = time.ticks_ms()
        elif time.ticks_diff(time.ticks_ms(), start) > 20000:
            ota.confirm()
            return


async def main():
    global pub
    pub = Publisher(state, get_names=lambda: texts, set_names=set_texts, names_extra=status,
                    routes={"/update": ota.handle, "/bus": log.handle, "/device": device.handle,
                            "/ir": remote.handle, "/control": control.handle,
                            "/wifi": net.handle, "/": net.page})
    log.clear(time.ticks_ms())
    asyncio.create_task(net.task(wifi_result))
    await asyncio.sleep(0.1)            # Wi-Fi starts before the server opens the socket
    await pub.serve()                   # serves as soon as there is a network
    asyncio.create_task(confirm_update())
    asyncio.create_task(remote.watch_knob())
    await listen()                      # the listener starts right away, with or without Wi-Fi


asyncio.run(main())
