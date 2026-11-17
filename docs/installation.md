# Current install: the Pico in the middle, between the controller and the display

Built and working since 2026-10-29 (option 3b in `history/interception-options.md`). The amp's display was desoldered.
Pins 1–3, 15 and 16 were soldered back to the board; pins 4–14 no longer go into it:

- **Controller side**: Dupont wires soldered into holes 4–14 of the lower board.
- **Display side**: the wires soldered to the top ends of the display pins (the same ones as the old sniffer, same
  colours).

Program: `firmware/proxy.py`. `main.py` imports `escuta.py`, which only imports `proxy.py`, because `main.py` can only
be replaced over the cable.

## Wiring

Pico pin 1: the corner next to the USB. Pins 1–20 are on one row and 21–40 on the other (40 sits opposite 1, also next
to the USB).

### Controller side: lower wires → Pico

| Board hole | Signal | Pico | Physical pin |
|---|---|---|---|
| 4 | RS | GP3 | 5 |
| 5 | RW | GP4 | 6 |
| 6 | E | GP2 | 4 |
| 7–14 | D0–D7 | GP5–GP12 | 7, 9, 10, 11, 12, 14, 15, 16 |

### Display side: upper wires → Pico

| Display pin | Signal | Wire | Goes to | Physical pin |
|---|---|---|---|---|
| 1 | GND | black | GND | 3 (any GND will do: 3, 8, 13, 38…) |
| 2 | +5 V | red | **VSYS** | **39** (never 40, VBUS) |
| 4 | RS | yellow | GP16 | 21 |
| 5 | RW | orange | **GND** | 23 |
| 6 | E | brown | GP17 | 22 |
| 7–10 | D0–D3 | green, white, grey, purple | nothing (ends insulated with tape) | — |
| 11 | D4 | blue | GP18 | 24 |
| 12 | D5 | white | GP19 | 25 |
| 13 | D6 | grey | GP20 | 26 |
| 14 | D7 | purple | GP21 | 27 |

- Contrast (3) and backlight (15, 16) still come from the amp's board.
- The display runs in 4-bit mode with RW on GND: it only receives and never sends 5 V back to the Pico. The Pico's
  3.3 V is enough for it, with no level shifter (tested on the bench, `bench-wiring.md`).
- Since the white, grey and purple wires repeat, each one is labelled with its pin number.

### Four wires to control the amp (2026-11-06)

Soldered under the board, without resistors. Programs: `firmware/ir.py`, `firmware/panel.py` and `firmware/control.py`.

| Point on the board | Signal | Pico | Physical pin | Use |
|---|---|---|---|---|
| Signal leg of the IR receiver (chip leg 12) | IR | GP15 | 20 | The Pico pulls it to 0 for the pulses |
| E1 of the volume encoder (chip leg 22) | Knob | GP14 | 19 | Read only |
| Function button (K7) lead connected to chip leg 6 | P6 | GP0 | 1 | Read only |
| Function button (K7) lead connected to chip leg 13 | P13 | GP1 | 2 | The Pico pulls it to 0 to "press" |

- **GP15:** never driven to 1. Only the direction changes, at 2 mA. The line is pulled up by about 40 kΩ inside the
  receiver, so pulling it down costs about 0.1 mA.
- **Program before the wire:** the RP2350 boots with a pull-down, which can load the line. `proxy.py` turns it off right
  at startup. While the Pico restarts, the remote may fail for a few seconds.
- **Commands:** the Pico sends the same bits as the remote, as seen after the receiver, with no carrier. The timings are
  the ones measured on the line with the real remote. With the Broadlink timings, about 5% longer, the controller did
  not react.
- **Wake by the knob:** with `power` = `standby`, two E1 changes within 1 s send `power_toggle`, at most once every 5 s.
  With `power` = `null`, nothing happens: after the Pico restarts or the amp is plugged in, the Pico only knows about
  standby after seeing the amp enter that state.

- **Function button:** the controller pulses leg 6 and reads leg 13. When pressed, the button connects the two. The PIO
  imitates this: inside each long pulse on GP0, it pulls GP1 to 0. GP1 never goes to 1. In about 1 click out of 8, the
  amp also switches the input to PHONO, for no known reason, and `control.py` restores the previous input.
- **Symptom of a solder bridge:** on 2026-11-06, after soldering P6 and P13, any key on the remote sent the amp to
  PHONO, while the front button worked. It went away after checking the solder joints. If it comes back, look at these
  points first.

Routes and commands: `api-state.md`.

### Checking the cut (multimeter on continuity, amp unplugged)

- Lower wire of hole N × display pin N, for N = 4 to 14: **no beep**.
- Display pin 1 × board GND, and pin 2 × +5 V: **beep**.

## What the program does

- **Reads the controller** (`sniffer.py`): on each falling edge of E, the PIO reads the 11 wires, and DMA copies the
  words into a ring buffer. Nothing is lost while Python handles the Wi-Fi.
- **Answers "free"** (`busy.py`): the controller asks "busy?" before each command and each character, and releases only
  D7 to do so. On each read (RW = 1 on the rising edge of E), the PIO pulls D7 to 0 until E falls.
- **Draws** (`hd44780.py`, `names.py`, `lcd1602.py`): after 2 ms without writes, the screen is complete. The Pico
  replaces the names and sends the display only the lines that changed, with no flicker. Custom characters (the bars)
  and "display on/off" follow the controller's. Every 30 s it resyncs 4-bit mode and rewrites everything, without
  clearing the screen, to fix any error caused by noise on the wires.
- **Controls the amp** (`ir.py`, `ir_codes.py`): the PIO pulls the IR line to 0 for the timings that DMA delivers.
  Between one timing and the next, the line is released. The same file tracks the volume knob.
- **Makes direct settings** (`control.py`, `panel.py`): takes the request and walks the amp's menus with IR and the
  Function button, checking each step on the display.
- **Publishes** the state (`amp_state.py`, `web.py`). The state always shows the original names ("TUNER"), plus the
  custom name in `input_name`.

### Safety rule

GP2–GP12 receive 5 V from the amp, with no series resistors. They must **never** be outputs driving 1, because that
would fight the controller. The only one that becomes an output is GP12 (D7), and only to 0: the output value is fixed
at 0, only the direction changes, at minimum drive strength (2 mA). D7 belongs to the controller's P0, which is only
pulled up by the 4.7 kΩ resistor, so pulling it to 0 is always safe (~1 mA).

The four control wires follow the same rule. GP0 and GP14 are inputs only. GP1 and GP15 only pull to 0, at 2 mA, and
never go to 1.

## Power from the amp

The red wire (display pin 2, +5 V) goes to the Pico's **VSYS, pin 39**. This 5 V is also present in standby, so the
Pico stays on whenever the amp is plugged in, and boots together with the controller.

On the row of pins 21–40, with the USB facing up: the 1st pin in the corner, right by the USB, is **40 (VBUS, do not
use)**; the 2nd is **39 (VSYS)**; the 3rd is 38 (GND).

**Why VSYS and not VBUS:** VBUS (40) is wired directly to the USB connector. Between VBUS and VSYS there is a diode
inside the Pico, which keeps the amp's 5 V from reaching the computer.

### USB rule

With the red wire on VSYS, **do not plug in the USB while the amp is unplugged**. The USB would back-feed the amp's
panel through the Pico, which can damage the amp's 5 V regulator. This happened on 2026-10-29: with the USB plugged
in, the controller booted and drew the screen. To use the cable, with the amp unplugged, **disconnect the red wire
first**.

A 1N5817 Schottky diode in the red wire (anode on the display, cathode on VSYS) would remove this rule.

With the Pico inside the amp, update over Wi-Fi only (`wifi-update.md`).

## Without the Pico

The controller asks "busy?" before each character and, without an answer, keeps asking forever. **Without the Pico,
the amp's display does not update.** To go back to the original, connect each lower wire to the upper wire with the
same number (11 jumpers).

## Diagnostics

- **`http://sp103.local/names`**, field `proxy`:
  - `reads` and `writes`: controller reads and writes since the Pico booted.
  - `busy_high`: reads in which the controller saw "busy" after the Pico was already answering. **Must stay at 0.** At
    boot, the controller waits a few milliseconds while the Pico starts; those reads do not count.
- **Bus log:** the last 8192 words (about 50 screens), with timestamps (the Pico sets its clock from the internet).
  `GET /bus.json` returns the statistics.
  1. Clear the log: `curl -X POST http://sp103.local/bus/clear`.
  2. Do what you want to study on the amp and note the time.
  3. Download the log: `curl http://sp103.local/bus.csv -o bus.csv`.
  4. See the assembled screens: `python3 tools/ler_bus.py bus.csv` (with `--palavras`, each word too).
- **`http://sp103.local/ir`**: the IR line should sit at 1 when idle, and `knob_edges` should increase when turning
  the volume.
- **After the Pico restarts on its own** (an update, for example), the display stays empty until the controller sends
  the next screen (turn the volume or change input). This does not happen when the amp is plugged in: both boot
  together.

## Tests

- `python3 tools/test_proxy.py`: runs `proxy.py` on the computer with the `.lac` captures and checks every screen on
  the display, with the names applied. It also checks that RW does not change during the E pulse, the rule `busy.py`
  relies on.
- Tested on the Pico over the cable (2026-10-29): the `busy.py` program pulls D7 only on reads; and on the amp, once the
  Pico started answering, no read returned "busy".

## Open

- **Knowing the state right after a restart.** Standby comes from the screens (`api-state.md`), so it stays `null`
  until the amp changes state. Reading the front LED (chip legs 26 and 27, a read-only wire on GP13) would solve this.
