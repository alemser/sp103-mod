# Bench: wiring the spare display (blue 1602) to the Pico 2 W

> GP16–21 are the same pins that now draw on the amp's display (`installation.md`). On the bench, the spare display
> takes that place, powered from USB.

**4-bit** mode, with **RW tied to GND**: the Pico only writes and never reads. That way the display never sends 5 V back
to the Pico, and level shifters are not needed. Pins GP2–GP12 stay free for the controller side.

Pico pin 1: the corner next to the USB. Pins 1–20 are on one row and 21–40 on the other
(40 faces 1, also next to the USB).

| Display pin | Name on the display | Pico physical pin | Name on the Pico | Notes |
|---|---|---|---|---|
| 1 | GND | 3 | GND | |
| 2 | VDD | **40** | VBUS (5 V from USB) | ⚠️ check twice: never on a GPIO |
| 3 | VO | 8 | GND | tied straight to GND = maximum contrast (works well on this blue display); trimpot optional |
| 4 | RS | 21 | GP16 | |
| 5 | RW | 23 | GND | fixed at 0 = write only |
| 6 | E | 22 | GP17 | |
| 7 | D0 | — | — | free |
| 8 | D1 | — | — | free |
| 9 | D2 | — | — | free |
| 10 | D3 | — | — | free |
| 11 | D4 | 24 | GP18 | |
| 12 | D5 | 25 | GP19 | |
| 13 | D6 | 26 | GP20 | |
| 14 | D7 | 27 | GP21 | |
| 15 | BLA (light +) | 36 | 3V3 | start at 3.3 V; if it is too dim, we change it |
| 16 | BLK (light −) | 28 | GND | |

## Trimpot (contrast, optional)

On the bench (2026-10-23) VO was tied straight to GND (Pico pin 8) and the text looked good.
To adjust the contrast, use the trimpot as a variable resistor: middle leg on VO, one end on a free GND
(8, 13, 18 or 33) and the other end loose. Or build the full divider below.

| Trimpot leg | Connects to |
|---|---|
| end 1 | Pico pin 40 (VBUS, 5 V) |
| middle | VO (display pin 3) |
| end 2 | Pico pin 38 (GND) |

With the display powered, turn the trimpot until a row of little squares appears on line 1 (display not yet
initialised). Then back off a little, until the squares are faint.

## Before plugging in the USB

- [ ] VDD is on pin **40** (and not on 39, VSYS, or on a GPIO).
- [ ] No stripped wire touches its neighbour.
- [ ] The jumper between Pico pins 1 and 2 has been removed (it was only for the analyser).

## Result (2026-10-23)

It worked first time with the Pico's 3.3 V signals, without a level shifter.
With nothing on VO the screen is blue and empty: VO needs to go to GND (or to the trimpot).
Test program: `firmware/demo_telas.py` (see the instructions in the file itself).
