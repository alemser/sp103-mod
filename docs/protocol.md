# How the SP103 controller talks to the LCD (findings from the captures)

Source: captures in `captures/`, decoded with `tools/hd44780_decode.py`.

## Volume: `01-volume-c.lac` (2026-10-23, one click of the knob)

Screen after the click:

```
┌────────────────┐
│Volume -28.75 dB│
│■■■■■■■■■■      │   <- 10 custom characters (code 0x00) + 6 spaces
└────────────────┘
```

- **8-bit bus.** E pulses last 10.5 to 22.5 µs (sometimes longer). It is a slow controller, and 2 MHz sampling is
  enough (21 samples in the shortest pulse).
- **Reads the busy flag before every command and every character.** The per-character sequence is:
  1. read (RS=0, RW=1): busy flag + address counter
  2. `Set DDRAM addr` command (moves to the column)
  3. read (RS=0, RW=1)
  4. character write (RS=1)

  That is about 230 µs per character. It does **not** use address auto-increment: it positions every character.
- **One volume click redraws both lines in full:** 32 characters in about 8.6 ms.
- **Line 1:** `Volume -28.75 dB`.
- **Line 2, while changing the volume:** a **bar graph** made of custom character `0x00` (probably a full block).
  Length: 10 of 16 columns for -28.75 dB, i.e. proportional to (78.75 − 28.75) / 78.75 ≈ 63 %. On screen, the bar
  replaces the input name (confirmed visually).
- **Reads:** the busy flag never showed up as 1 in this capture. The LCD responds quickly relative to the controller's
  pace.
- **Idle:** between writes, RS stays at 1 and the data lines stay latched at the last byte written (they do not return
  to 0xFF). E stays at 0.

### What this means for the project
- **The final Pico must answer the controller's reads** (RW = 1), at least with busy flag = 0. If it does not, the
  controller may hang waiting.
- **The "cut only the E pin" option is unlikely**, because the data lines are not free when idle. The realistic path
  is to intercept the signals (cut pins 4 to 14) or desolder the LCD. Done: the LCD was desoldered on 2026-10-29
  (`installation.md`).
- **Custom character 0x00** is defined at some point (probably at power-on). The power-on capture should show the
  `Set CGRAM addr` commands with its pattern.

## Phono input: `04-phono-b.lac` (2026-10-23)

```
┌────────────────┐
│Volume -28.75 dB│
│PHONO           │
└────────────────┘
```

- When changing input, the controller also **redraws both lines in full** (about 8.5 ms), with the same pattern
  (read → address → read → character).
- Line 2 = input name, padded with spaces to 16 columns.

## Inputs: `05-tuner` to `09-dab` (2026-10-23)

Same pattern as Phono: both lines are redrawn, and line 2 holds the input name padded with spaces.

| Button | Line 2 |
|---|---|
| Phono | `PHONO` |
| Tuner | `TUNER` |
| Tape/Aux | `TAPE/AUX` |
| CD | `CD` |
| DVD | `DVD` |
| DAB | `DAB` |

## At power-on: `03-liga.lac` (2026-10-23)

Captured with a **pattern trigger** E=1, RS=0, RW=0 (channels 1–3, pattern `100`), at 1 MHz, with a jumper between the
Pico's GP0 and GP1. The edge trigger does not work: during reset the controller leaves E, RS and RW at 1
(`00-amp-onoff.lac`).

Sequence:
1. `0x01` Clear → `0x06` Entry mode (increment) → `0x0C` Display ON (no cursor) → `0x38` Function set
   (8 bits, 2 lines, 5x8). Function set comes **last**, which is unusual, but it works because the LCD already powers
   up in 8-bit mode.
2. `0x40` Set CGRAM addr 0 followed by **64 bytes**: the 8 custom characters (below).
3. **Everything repeats about 64 ms later** (init + CGRAM again).
4. Both lines are filled with spaces (positioning each character) and then comes the welcome screen:

```
┌────────────────┐
│    ACOUSTIC    │
│    SOLUTIONS   │
└────────────────┘
```

The capture (190 ms) ends on the welcome screen. The change to the normal screen happens later.

### Following screens: `03-liga-telas.lac` (burst, 10 segments of 19 ms at 1 MHz)

Captured by arming the edge trigger (E) as soon as "ACOUSTIC SOLUTIONS" appeared, then turning the volume to fill the
remaining segments. The D1 wire had no contact, but the text can be recovered from context (bit 1 was always read as 0).

Full power-on sequence (about 4 s in total):

```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│    ACOUSTIC    │ --> │Amplifier SP103 │ --> │Volume -28.75 dB│
│    SOLUTIONS   │     │ SW version 1.0 │     │DAB             │   <- last input used
└────────────────┘     └────────────────┘     └────────────────┘
```

Version `1.0` was confirmed on screen by the owner.
After changing the volume, line 2 becomes the bar and, a while later, **goes back by itself** to the input name.

Note: the software did not save `LoopCount` in the `.lac` file for this burst capture. The script detects the burst
from the data size.

### Custom characters (CGRAM)

| Code | Pattern (8 rows, 5 dots) | Use |
|---|---|---|
| 0x00 | `00 1F 11 11 11 11 1F 00`: **empty box** (outline) | volume bar |
| 0x01 | only the bottom row filled | level 1/7 |
| 0x02 | bottom 2 rows | level 2/7 |
| 0x03 | 3 rows | level 3/7 |
| 0x04 | 4 rows | level 4/7 |
| 0x05 | 5 rows | level 5/7 |
| 0x06 | 6 rows | level 6/7 |
| 0x07 | 7 rows (almost full block) | level 7/7 |

Codes 0x01–0x07 form rising "vertical bars", probably used in the Function menus (bass/treble?) or in some animation.
We have not seen where yet.

## Function, 1st press: `13-function-1.lac` (2026-10-23)

Wires with poor contact in this capture: RW and D4 always at 0, and RS came loose at the start. Even so, the fixed
pattern (read → address → read → character) makes it possible to separate address and data in groups of 4 pulses, and
D4 can be recovered from context. Reconstruction (still to be confirmed on screen):

```
┌────────────────┐
│Bass -10 dB     │
│  ■■■■■<>       │   <- bipolar bar: "<>" in the centre (columns 7–8), 5 boxes on the left = -10 dB
└────────────────┘
```

Second recording of the same press (only RW failed), with a different bass value:

```
┌────────────────┐
│Bass   2 dB     │   <- value right-aligned in columns 5–7 ("-10", "  2"), no "+" sign
│       <>■      │   <- 1 box to the right of the centre = +2 dB
└────────────────┘
```

- Line 2 is written **from the centre outwards**: columns 7, 8 ("<", ">"), 9…15 and then 0…6.
- Each box (character 0x00) seems to be worth 2 dB, consistent with the PT2314 bass steps.

## Function, all menus: `13-function-todos.lac` (burst, 2026-10-23)

Decoded with `--sem-rw` (RW dropped out now and then). It takes 6 Function clicks to get back to the normal screen:

```
1 ┌────────────────┐  2 ┌────────────────┐  3 ┌────────────────┐
  │Bass   2 dB     │    │Treble   0 dB   │    │Balance <level> │
  │       <>■      │    │       <>       │    │       <>       │
  └────────────────┘    └────────────────┘    └────────────────┘
4 ┌────────────────┐  5 ┌────────────────┐  6 ┌────────────────┐
  │   Loudness     │    │   Speakers     │    │Volume -15.00 dB│
  │ < OFF >   ON   │    │   OFF   < ON > │    │DAB             │
  └────────────────┘    └────────────────┘    └────────────────┘
```

- Bass and Treble: right-aligned numeric value (3 characters) + bipolar bar with "<>" in the centre.
- Balance: "<level>" when centred (still to see how it looks off-centre).
- Loudness and Speakers: two options, with the selected one between "< >".
- Segments 7 to 10 are volume clicks (with D4 failing: "Foleme" = "Volume").

## Balance while turning the knob: `15-balance.lac` (burst, 2026-10-23)

Each knob click redraws the whole screen, in steps of **1.25 dB** (the PT2314 speaker attenuator):

```
┌────────────────┐        ┌────────────────┐
│Balance -5.00 dB│  ...   │Balance-10.00 dB│   <- with two digits, the space after "Balance" disappears
│       <>■      │        │       <>■■     │   <- 1 box per 5 dB, on this side of the centre
└────────────────┘        └────────────────┘
```

The 10 segments went -1.25 → -12.50 dB, always in the same direction. Write order: all of line 1, then "<" ">"
(columns 7–8), columns 0–6 of line 2 and finally columns 9–15.
Still to see the other side: which side the bar is on, and whether the number changes sign or gains L/R.

## Remote control and power-off (observed by the owner, 2026-10-23)

- The remote does exactly the same as the panel buttons, with the same screens.
- On power-off, the display goes **blank**. Correction from 2026-10-29, from the Pico's bus log: the controller writes
  spaces to all 32 positions (DDRAM 0x00–0x0F and 0x40–0x4F, with no "Clear display") and stops. That is why it seemed
  to write nothing. Coming out of standby, it draws the normal screen directly (`Volume … / DAB`), with no "Clear
  display" and no "ACOUSTIC SOLUTIONS". When it gets mains power, the screen is blank for about 70 ms, but after a
  "Clear display" (`03-liga.lac`): this is how the Pico tells the two blanks apart (`amp_state.py`,
  `power: "standby"`).

## Balance to the other side: `15-balance-b.lac` (burst, 2026-10-23)

The same negative numbers (-1.25 → -12.50 dB). Only the **bar** switches sides and grows to the **left** of the "<>":

```
┌────────────────┐
│Balance-10.00 dB│   <- same as the other side: line 1 does not say which channel is attenuated
│     ■■<>       │
└────────────────┘
```

## Port electrics and busy flag reads (2026-10-24)

Measured with the multimeter (amp in standby, same values with the amp on) and with the Pico, during the tests of
writing without cutting (`history/interception-options.md`; the tools are in the git history).

| Wire | Port | Idle | When driven to 1 | Measurement |
|---|---|---|---|---|
| RS | P3.0 | 1 | weak (8051 pull-up) | 4.94 V; 0.168 mA to GND |
| RW | P3.1 | 0, strongly | **weak**: the Pico pulled it to 0 with only 2 mA | 0.00 V; 0.057 mA |
| E | P2.7 | 0, strongly | not tested (the Pico never raises E) | 0.03 V; 0.306 mA |
| D0–D7 | P0 | last byte | only via the 4.7 kΩ pull-ups (R907/R908) | ~1 mA when pulling a 1 to 0 |

- **To read the busy flag, the controller releases only D7.** The other wires stay latched at the last byte written.
  When the Pico turned a read into a write (by pulling RW), the LCD received 0xD6: the previous character, 'V' (0x56),
  with bit 7 set. The firmware probably does `SETB P0.7` and tests only that bit.
- **Busy flag at 1 → it asks again.** With bit 7 at 1 ("busy"), the controller did another read and then carried on
  normally: there is no timeout and no visible error.
- **RW rises ~21 µs before E** on reads; E pulses last 10 µs or more.
- **Delayed redraw (not confirmed):** in one log, after each event (volume or input change), the controller redrew
  immediately and **again, 2 to 6 s later**. Since `/bus` does not log buttons, the second screen may have come from a
  second press. With the proxy this no longer matters: every screen is drawn with the right names.
- **The LCD ignores command 0x00** (test 2): it changes neither address nor mode. Switching from TUNER to DAB with 0xC0
  zeroed, the screen showed "TAB".
- **On the rising edge of E, RS, RW and the data are already in place** (commands and characters), and stay that way
  until the falling edge.
- **Noise on E with long wires:** with ~20 cm wires soldered to the pin ends, the E edge "shakes" (false pulses of up
  to ~1 µs, also rare in the captures). The sniffer now only accepts pulses of 3 µs or more.

## With the Pico as proxy (2026-10-29)

With the display disconnected from the controller, only the Pico answers the busy flag reads (`firmware/busy.py`):

- **At power-on, the controller waits for the Pico.** The Pico takes a few milliseconds to load the answering
  program; during that time, the controller read "busy" ~900 times in a row and then carried on normally, with no
  error. This confirms there is no timeout.
- **After the first "free" answer, no read returned "busy".** D7 pulled to 0 on the rising edge of E arrives in time,
  and the read → write sequence stays the same as in the captures.
- **The "display on/off" command (0x08–0x0F)** was read as "entry mode" by the model (`hd44780.py`) and by the
  decoder. Fixed; it does not change the text.

## Status

**Capture phase complete (2026-10-23).** All of the controller's screens are recorded above. The Pico has reproduced
these screens on the amp's display, with the custom names, since 2026-10-29.
