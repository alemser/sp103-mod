# Brief: custom text on the front LCD of the Acoustic Solutions SP103 (Raspberry Pi Pico 2 W)

Summary from the conversation with Claude (cloud), 2026-10-21. It stays as the project's reference; the current state
is in `README.md` and in "Progress", at the end.

## Goal
Change what the SP103 amplifier's original front LCD shows (for example, "PHONO" becomes "Turntable", custom volume, a welcome message and, later, the track name coming from OceanO). The original LCD, the original controller and all the amplifier's functions stay intact. Everything must be reversible. The owner is a hobbyist, so the explanations should be step by step.

## Hardware facts
Verified from the photos:
- Front board: "SP103 AMPLIFIER CONTROL BOARD 3", DSP-ISS2, dated 2007/06/08.
- Display: standard 16x2 character LCD module (marked LCD1A), yellow-green backlight, a single row of 16 pins, separate A/K pads on the right. Contrast trimpot VR301.
- Controller: 40-pin DIP marked T9311DP / Y534D383 9353 / D2414 3323550. No datasheet and firmware cannot be modified. It has a crystal with two 22 pF capacitors and two 9-pin 4.7k resistor networks (R907/R908, "9P4K7").
- IC801 = 24C01 I2C EEPROM (pin 5 = SDA, pin 6 = SCL, pin 4 = GND). The volume is a rotary encoder, so the volume is fully digital.
- Audio processor: PT2314 (I2C), on the input board. Steps of 1.25 dB, from 0 to -78.75 dB.
- The display shows, for example, "Volume -78.75 dB" on line 1 and "PHONO" on line 2.

Inferred, not yet confirmed:
- HD44780-compatible LCD on a parallel bus. Pinout: 1 VSS, 2 VDD, 3 VO, 4 RS, 5 RW, 6 E, 7–14 D0–D7, 15/16 A/K. The orientation of pin 1 still needs to be confirmed.
- 8051-family controller: pin 20 = GND, pin 40 = +5 V.
- Unknown: 4-bit or 8-bit mode, and whether RW goes to GND or the controller reads the busy flag.

## Chosen approach
1. Measure first, without touching anything:
   - Continuity with the multimeter, with the amp unplugged. Check LCD pin 5 against GND, see whether pins 7–10 are connected or floating (4-bit mode), map LCD pins 4–14 to the controller legs, and see whether pins 5/6 of the 24C01 reach connector J2.
   - Logic analyser with the amp on: the LCD bus (RS, E, data) and I2C, while changing input and turning the volume.
2. Bench phase: the Pico only listens to the original LCD pins, as inputs, with a common GND. It drives a spare 1602 on the breadboard. During this phase the Pico is powered from the laptop's USB, with the laptop on battery.
3. Final install: cut only the signal pins (4–14) between the LCD board and the control board. The lower stub (from the controller) goes to a Pico input, and the upper one (to the LCD) receives a Pico output. To revert, just connect each pair of stubs. The Pico sits on a MonkMakes Prototype PCB, on nylon standoffs.
4. Power: VSYS from LCD pin 2 (+5 V) through a 1N5817 Schottky diode, with GND on LCD pin 1.
5. Track names: the Orange Pi Zero 2W (OceanO) sends them over Wi-Fi to the Pico 2 W.

## Electrical constraints
- The Pico's GPIO is 3.3 V. The RP2350 inputs tolerate 5 V only while the chip is powered.
- 3.3 V outputs into the 5 V LCD: test on the bench. If they are not reliable, use BSS138 level shifters.
- RP2350 erratum E9: avoid the internal pull-downs on inputs.
- Never power VSYS and USB at the same time without the diode.
- Never touch the 230 V side. Connect and disconnect wires only with the amp unplugged.

## Software stages
1. Drive the spare 1602 from the Pico (hello-world and contrast test).
2. Passive HD44780 sniffer via PIO (latch on the falling edge of E, 4- and 8-bit modes) that rebuilds the 16x2 buffer and prints it on serial.
3. Rewrite layer ("PHONO" → "Turntable") that renders on the spare LCD.
4. Later: a Wi-Fi endpoint for OceanO to send "now playing" (temporary overlay).

The "Decided architecture" section (at the end) updates this list. The install that was actually built is in
`docs/installation.md`: the display was desoldered, instead of cutting the pins, and the Pico sits in the middle.

MicroPython with rp2 PIO if the timing allows, otherwise the C SDK. Simple, well-commented code.

## Findings from the petervis.com photos (2026-10-22)

Photos in `docs/img/petervis/`, of the same board model ("SP103 AMPLIFIER CONTROL BOARD 3", DSP-ISS2, 2007/06/08).

- The contrast trimpot is called **VR901** (10k, marked 103), not VR301. It sits to the left of the LCD.
- The LCD module has a row of 16 pins in the top left corner and the backlight **A** and **K** pads on the right side.
  The trimpot is near the left end, which suggests pin 1 is the leftmost one (seen from the front). Still to confirm.
- In the photo of the solder side, only some of the 16 pins have a thin trace going to the controller, in a bundle of about 6 or 7 traces.
  This matches **4-bit mode** (RS, E, D4–D7, with RW to GND), but it is only a hypothesis until measured.
- The input board ("SP103 IO BOARD ISS1 VER 1.1") has **two PT2314s** (U52 and U53) and connector **CON51**
  with 4 ways: **GND, CL, DA1, DA0**. That is, a shared SCL and one SDA for each PT2314, because both have the same
  fixed address. A white 4-wire cable connects CON51 to the front board.
- The display shows, for example, "Volume -26.25 dB" / "CD".

## Multimeter measurements (2026-10-22)

Answered. See the full map in `docs/analyzer-wiring.md`:
- The bus is **8-bit**: D0–D7 on legs 39–32 (P0).
- **RW does not go to GND**: it is on leg 11 (P3.1). RS on leg 10 (P3.0), E on leg 28 (P2.7).
- LCD pin 1 is the left end, seen from the front.

## Captures with the analyser (2026-10-23)

Done. Details in `docs/protocol.md`:
- The controller **reads the busy flag** before every command and every character. The final Pico must answer these reads.
- It **redraws both lines in full** on every event (volume, input, menu), positioning each character (about 8 ms per screen).
- The data lines stay latched at the last byte when idle, so cutting only the E pin should not be enough.
- Screens: welcome, model and version, volume + input/bar, Function menus (Bass, Treble, Balance, Loudness, Speakers).
- Does the controller send the PT2314 commands on the same I2C bus as the 24C01?

## Decided architecture (2026-10-23)

> Update from 2026-11-06: the Pico now also sends commands over the IR line, inside the amp
> (`installation.md`). It still does not replace the controller. The web pages are gone: the Pico only has an API, and
> the client is the app in the amp-link repository. The text below stays as a record of the original decision.

The Pico does **not** replace the controller and does **not** emit IR. IR control of the amp already exists in the
**groove-rig** project (Broadlink, API on port 7075, on the Orange Pi "oceano").

The two systems are independent: the Pico can publish state to any client, including groove-rig, but it never makes
requests, sends IR or asks another device to trigger an amplifier redraw.

The Pico's role:
1. **Observe** everything the controller writes to the LCD.
2. **Keep the amp's state in memory**, updated on every change.
3. **Offer that state over the network** to anyone who wants it: groove-rig, an app, a web page.
4. Rewrite or draw the screens on the LCD (the original goal).

### State

```json
{
  "power": "on",
  "volume_db": -28.75,
  "input": "PHONO",
  "bass_db": 2,
  "treble_db": 0,
  "balance": { "side": "R", "db": -5.0 },
  "loudness": false,
  "speakers": true,
  "screen": "normal",
  "lcd": ["Volume -28.75 dB", "PHONO           "],
  "updated_at": 1234567
}
```

- A **screen reader** recognises each redrawn screen and updates only the fields it shows.
  The "Bass 2 dB" screen, for example, updates only `bass_db`.
- The balance side (L/R) comes from the position of the bar: the number is negative on both sides.
- Volume and input always appear on the normal screen. Bass, treble, balance, loudness and speakers only appear when
  someone opens the Function menu. Until then they stay "unknown" (`null`), or keep the last value seen, stored in
  flash. The controller stores these values in the EEPROM, so the last value seen usually still holds after power-off.
- Later, optional: also listen to the CON51 I2C (the real PT2314 values, all sent when the amp powers on).

### Interface (Wi-Fi)

| Endpoint | Purpose |
|---|---|
| `GET /state` | the JSON above |
| `GET /events` | Server-Sent Events: a notice on every change (so groove-rig can do closed-loop control, e.g. "go to -30 dB") |
| `GET /` | simple page to see the state on a phone |
| `GET /bus` | bus statistics and download of the latest words (CSV with timestamps) |
| `GET /update` | program update over Wi-Fi, password-protected (`docs/wifi-update.md`) |

Wi-Fi rather than Bluetooth: OceanO and groove-rig are already on the network, and the phone's browser is enough (no
app).

### Open

- **Knowing when the amp turns off.** On power-off, the controller writes nothing to the LCD. The options are to power
  the Pico separately and measure the amp's 5 V on a GPIO (with a divider), or for groove-rig to treat "Pico not
  responding" as "amp off". Decide at the final install.

### Order of stages

| # | Stage | Needs the amp? |
|---|---|---|
| 1 | Bench: the Pico draws the captured screens on the spare display, from a state | no |
| 2 | Screen reader (screen → state), tested on the Mac with the `.lac` captures | no |
| 3 | Wi-Fi: `/state`, `/events` and page, with test state | no |
| 4 | Real sniffer (PIO) on the amp's LCD bus | yes, listening only |
| 5 | Optional consumption of `/state` and `/events` by groove-rig | yes |
| 6 | Final install (intercept the LCD, power, power detection) | yes (done on 2026-10-29, except power detection) |

### Progress

- **Stage 2 done (2026-10-23):** `firmware/amp_state.py` (screen reader, MicroPython-compatible) and
  `tools/test_amp_state.py` (18 hand-written screens + replay of the `.lac` captures). Every good screen in the
  captures becomes state; screens corrupted by a loose wire are rejected (`screen: "unknown"`, fields unchanged).
- Below 5 dB of balance the bar does not appear, so the side stays `null` until it goes past 5 dB.
- Still to confirm which channel the bar indicates (bar on the right = right channel attenuated, or the sound moved to
  the right?).
- **Stage 1 done (2026-10-23):** `firmware/lcd1602.py` (4-bit driver, write-only), `firmware/sp103_screens.py`
  (state → screen, with the amp's CGRAM) and `firmware/demo_telas.py`. All screens and the 8 glyphs show correctly on
  the blue 1602, with the Pico's 3.3 V signals (no level shifter). VO went straight to GND.
  Poor contact on wires just pushed into the holes scrambles 4-bit mode; the program resets the display before each
  screen to recover by itself. Permanent fix: solder a pin header.
- **Stage 3 done (2026-10-23):** Wi-Fi in the background (with no network, the display carries on normally),
  `/state`, `/events`, `/names` and page; input names and boot texts customisable from the page
  (`firmware/names.json` on the Pico); `main.py` runs everything by itself at power-on.
- **Interception (stage 6), analysis (2026-10-23):** overwriting in parallel is not feasible (the controller drives E
  and data strongly) and the T9311 has no socket. Options in `docs/interception-options.md`.
- **Stage 4, firmware ready (2026-10-24):** `firmware/escuta.py` + `sniffer.py` (PIO + circular DMA) + `hd44780.py`.
  Tested with the captures (`tools/test_sniffer.py`) and on the Pico without the amp (`tools/teste_sniffer_pico.py`);
  `main.py` now runs the sniffer. No series resistors, and the Pico powered from LCD pin 2 (5 V present even in
  standby) into VSYS.
- **Wi-Fi update and /bus page (2026-10-24):** `firmware/ota.py` + `main.py` (automatic rollback to the previous
  version) and `tools/enviar.py`, see `docs/wifi-update.md`. `firmware/buslog.py`: bus statistics and download of
  the latest words (8192 today) with timestamps (`tools/ler_bus.py` rebuilds the screens). Tested on the bench with a
  fake amp (`tools/teste_bus_pico.py`), including the automatic rollbacks.
- **Writing without cutting (2026-10-24 to 10-28), retired:** the Pico, in parallel with the display, only pulled wires
  to 0 and managed to show short names (REGA, TAPE), only from the second redraw on. Summary and lessons in
  `docs/interception-options.md`; the code is in the git history (up to `6be4eb2`).
- **Install inside the amp (2026-10-24):** the Pico sits inside, powered from LCD pin 2 (red wire to VSYS, pin 39);
  updates over Wi-Fi only (`tools/enviar.py`).
- **Stage 6 done: the Pico as proxy (2026-10-29):** display desoldered at pins 4–14 (option 3b). The Pico reads the
  controller, answers "free" to the busy flag (`firmware/busy.py`) and draws the screens with the custom names
  (`firmware/proxy.py`). Any text up to 16 characters, from the first screen. Tested on the amp and with the captures
  (`tools/test_proxy.py`). Install: `docs/installation.md`.
- **VU meter (2026-10-29):** optional, from the page. The data comes from groove-detector through a new bridge on the
  Orange Pi (`relay/`, UDP), without changing the detector. See `docs/vu.md`.
