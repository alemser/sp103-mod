# Wiring the logic analyser to the SP103 LCD

> The pin map below still applies. The analyser wiring was used for the captures on 2026-10-23; today LCD pins
> 4–14 are separated from the controller (`docs/installation.md`). To capture again, connect the analyser to the
> wires on the controller side (holes 4–14 on the board).

## Pin map (measured with a multimeter on 2026-10-22, amp unplugged)

LCD pins numbered from left to right, looking at the display from the front (pin 1 = left end).
T9311DP chip: legs 1–20 on the bottom row (left to right) and 40–21 on the top row
(left to right; leg 40 is at the top-left corner).

| LCD pin | Signal | Chip leg | Port (if 8051) | Notes |
|---|---|---|---|---|
| 1 | GND (VSS) | – | – | beeps with GND |
| 2 | +5 V (VDD) | – | – | **connect nothing** |
| 3 | VO (contrast) | – | – | beeps with GND (trimpot almost at minimum; normal) |
| 4 | RS | 10 | P3.0 | |
| 5 | RW | 11 | P3.1 | does **not** go to GND: the controller drives RW |
| 6 | E | 28 | P2.7 | |
| 7–14 | D0–D7 | 39–32 | P0.0–P0.7 | P0 needs pull-ups: they are the R907/R908 networks (9 × 4.7k) |
| 15 | A (backlight +) | – | – | not measured |
| 16 | K (backlight −) | – | – | beeps with GND |

**Conclusion:** an **8-bit** bus, and RW is driven by the chip (it can read the busy flag).

## Wiring on the Pico 2 W

Confirmed in the firmware code (`pinMap`): **Channel N = GP(N+1)** for channels 1–21.
Channels 22–24 are GP26–28, which are ADC pins and do **not** tolerate 5 V. Do not use those channels.

| Signal | LCD pin | Channel | Pico GPIO | Pico physical pin |
|---|---|---|---|---|
| GND | 1 | – | GND | 3 (or 8, 13) |
| E | 6 | CH1 | GP2 | 4 |
| RS | 4 | CH2 | GP3 | 5 |
| RW | 5 | CH3 | GP4 | 6 |
| D0 | 7 | CH4 | GP5 | 7 |
| D1 | 8 | CH5 | GP6 | 9 |
| D2 | 9 | CH6 | GP7 | 10 |
| D3 | 10 | CH7 | GP8 | 11 |
| D4 | 11 | CH8 | GP9 | 12 |
| D5 | 12 | CH9 | GP10 | 14 |
| D6 | 13 | CH10 | GP11 | 15 |
| D7 | 14 | CH11 | GP12 | 16 |

Tip: in the capture window, type the names in the fields below each channel (E, RS, RW, D0…D7).
That way the waveforms are readable and the script uses the names.

## Electrical safety

- **5 V on the inputs:** per the RP2350 datasheet, bank 0 GPIOs (except the ADC ones, GP26–29) tolerate 5 V
  **only with the Pico powered** (IOVDD = 3.3 V). So:
  1. Amp **unplugged**: connect the wires.
  2. Pico on the Mac's USB (laptop **on battery**).
  3. Only then plug the amp in.
  4. To finish: **first** unplug the amp, **then** the Pico's USB.
- **Protection resistor (recommended):** a 1 kΩ in series on each signal wire, close to the Pico. It does not get in the way
  at this speed and limits the current if the order above goes wrong.
- **Internal pull-downs (erratum E9):** the firmware does not enable any pull on purpose, but the RP2350 starts with the
  pull-down enabled. E9 only affects weak signals, and here all signals are driven hard
  (chip outputs or 4.7k pull-ups), so there is no problem for the capture.
- **Dupont wires:** fitted side by side on the pins (2.54 mm pitch), check that none touches its neighbour.
  Pin 2 (+5 V) stays **free**.

## Capture plan

With 11 channels, the firmware uses 16-channel mode: **about 196 thousand samples** fit per capture.

| Frequency | Maximum duration | Use |
|---|---|---|
| 25 MHz | ~7.8 ms | measure the E pulse width |
| 10 MHz | ~19.6 ms | see a write block in detail |
| 4 MHz | ~49 ms | power on the amp, change input (needs E pulse ≥ 0.75 µs) |
| 2 MHz | ~98 ms | long sequences (needs E pulse ≥ 1.5 µs) |

In every capture, use: channels 1–11, **Edge trigger on channel 01 with "Negative edge" unchecked**, presamples 512.

According to the firmware code (`NEGATIVE_CAPTURE` in `LogicAnalyzer.pio`), the "edge trigger" tests the pin's **level**:
- "Negative" fires as soon as the pin is at 0;
- "Positive" fires as soon as the pin is at 1.

E rests at 0, so only "Positive" waits for the pulse. Also, the pin is tested once per sample:
at low frequencies, an E pulse shorter than the interval between samples can go unnoticed.
That is why the first capture is done at 25 MHz.

1. **E pulse width (first capture):** amp on, 25 MHz, turn the volume.
   The script shows the minimum E width, and from that you choose the frequency of the next captures
   (at least 3 samples in the shortest pulse).
2. **Powering on the amp (initialisation sequence):** with the Pico already on and waiting for the capture, plug the amp in.
3. **Changing input:** for example, to PHONO.
4. **Turning the volume.**

If the capture fires without you touching anything, it means the controller redraws the screen by itself from time
to time. That is also an answer (question 3).

Save each capture with **File → Save** (`.lac` file) in `captures/` and run:

```
python3 tools/hd44780_decode.py captures/nome.lac
```

It shows:
- the commands (Function set, Clear, DDRAM address…) and the texts written, with the time in µs;
- the **reads (RW = 1)** and the busy flag;
- the screen rebuilt after each block and the minimum E pulse width.

## Questions the captures answer

1. Does the controller ever read the LCD (RW = 1)? If it does, the final Pico must answer those reads.
2. What is the initialisation sequence?
3. Is the text redrawn in full or only the characters that change? How often?
