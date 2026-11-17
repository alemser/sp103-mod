# Measurement plan: SP103 front board

> **Completed on 2026-10-22.** The results are in `docs/ligacao-analisador.md`.

Goal: find out how the controller (T9311DP) talks to the LCD, **without powering anything on the amplifier**.
At the end, we will know how many wires the logic analyser needs and where to attach them.

Fill in the tables as you measure. If something does not match what is expected, **write it down anyway**: the
unexpected is exactly what we want to find out.

---

## 0. Safety and preparation

- [ ] Amplifier **off and unplugged**. Wait **5 minutes** before opening it.
      The power supply capacitors take a while to discharge.
- [ ] Do not touch the power supply board or the transformer (230 V side). We will only work on the front board.
- [ ] Take **photos** of both sides of the front board (components and traces) before starting
      and save them in `docs/img/`. They help to follow the traces.
- [ ] Multimeter in **continuity** mode (sound/diode symbol). Touch one probe to the other:
      it must **beep**. If it beeps, the mode is right.

**How to measure continuity:** touch one probe to each point. If it beeps, the points are connected by a trace.
If it does **not** beep, switch the multimeter to **resistance (Ω, 20k range)** and measure again:

| Reading | Meaning |
|---|---|
| less than 10 Ω | direct connection (trace) |
| 10 Ω to 1 kΩ | connected through a series resistor; counts as "connected", note the value |
| about 4.7 kΩ | connected through the pull-up resistor (the R907/R908 networks) |
| no reading (OL / 1) | not connected |

Tip: measure on the **solder joints** on the underside of the board, where the probes sit more firmly.
Be careful that the probe does not slip and touch two joints at once.

---

## 1. How to count the pins

**40-leg chip (T9311DP controller)** and **8-leg chip (24C01, IC801)**: look for the
**notch** (half-moon) or the **dot** at one end of the chip. Seen **from above** (component side):

```
          notch
      ┌─────◡─────┐
   1  │●          │ 40          (on the 24C01:  1 ┤ ├ 8
   2  │           │ 39                          2 ┤ ├ 7
   3  │           │ 38                          3 ┤ ├ 6  = SCL
  ... │           │ ...               GND = 4 ┤ ├ 5  = SDA )
  20  │           │ 21
      └───────────┘
```

Pin 1 is next to the notch, and the count goes down one side and **back up the other**.
**Note:** seen **from below** (solder side), everything is **mirrored**: pin 1 moves to the other side.

---

## 2. Find GND and confirm the controller

Pin 4 of the 24C01 is GND for sure. We will use it as reference.

| # | Probe A | Probe B | Expected | Result |
|---|---|---|---|---|
| 2.1 | 24C01 pin 4 (GND) | controller pin **20** | beeps (8051: pin 20 = GND) | |
| 2.2 | 24C01 pin 8 (VCC) | controller pin **40** | beeps (8051: pin 40 = +5 V) | |
| 2.3 | 24C01 pin 4 (GND) | 24C01 pin 8 (VCC) | does **not** beep (otherwise, there is a short) | |

If 2.1 and 2.2 beep, the controller is from the 8051 family, and the rest of the plan holds as is.
If they do not beep, note which controller pin beeps with GND and with VCC, and let me know.

---

## 3. LCD orientation (where pin 1 is)

The LCD has a row of 16 pins. Measure **both ends of the row** against GND (24C01 pin 4):

| # | Probe A | Probe B | Result |
|---|---|---|---|
| 3.1 | pin at the **left end** of the row | 24C01 pin 4 (GND) | |
| 3.2 | pin at the **right end** of the row | 24C01 pin 4 (GND) | |

The end that beeps is **pin 1 (VSS)**. Mark that pin with a pen or a piece of tape.

Then confirm, counting from pin 1:

| # | LCD pin | Probe B | Expected | Result |
|---|---|---|---|---|
| 3.3 | pin 2 (VDD) | 24C01 pin 8 (VCC) | beeps | |
| 3.4 | pin 3 (VO) | middle pin of trimpot **VR901** (10k, left of the LCD) | beeps | |
| 3.5 | pins 15 and 16 (or A/K pads) | — | note where they go | |

---

## 4. The three main questions

### 4.1 Is RW (pin 5) connected to GND?

| LCD pin | Probe B | Result |
|---|---|---|
| pin 5 (RW) | 24C01 pin 4 (GND) | |

- **It beeped:** the controller only writes to the LCD. One less wire to capture.
- **It did not beep:** RW goes to the controller. We find which pin in section 5.

### 4.2 4-bit or 8-bit mode? (pins 7 to 10 = D0 to D3)

Measure each one against GND and then **against the neighbouring pins**:

| LCD pin | against GND | against VCC | Note |
|---|---|---|---|
| pin 7 (D0) | | | |
| pin 8 (D1) | | | |
| pin 9 (D2) | | | |
| pin 10 (D3) | | | |

- **All connected to GND, or floating (no solder/trace):** **4-bit mode**. Only D4–D7 carry data.
- **Each one goes to a controller pin:** **8-bit mode** (we confirm in section 5).

### 4.3 Does the I2C leave the front board?

The petervis.com photos show that the **input board** ("SP103 IO BOARD ISS1") has **two PT2314s**
(U52 and U53) and a 4-way connector, **CON51**, marked **GND, CL, DA1, DA0**:
a clock (SCL) shared by both and **a separate SDA for each PT2314**. This is needed because both
have the same fixed I2C address. The white 4-wire cable runs from CON51 to the front board.

| # | Probe A | Probe B | Result |
|---|---|---|---|
| 4.3a | 24C01 pin 5 (SDA) | each pin of the 4-wire cable connector on the front board | pin no. ___ |
| 4.3b | 24C01 pin 6 (SCL) | each pin of that same connector | pin no. ___ |
| 4.3c | each pin of that connector | controller legs | CL → ___, DA0 → ___, DA1 → ___ |

CON51 is a great place to attach the analyser to the I2C: just 3 signals plus GND, and the pins are accessible.

---

## 5. LCD → controller map

For each LCD pin, keep one probe on it and **run the other over the 40 legs** of the controller
until it beeps. Start with the suggested groups, because that is where they usually are:

- **Legs 32 to 39** (8051 port P0): this port needs external pull-ups (the 4.7k R907/R908
  networks). But in the photos the networks sit on the side of legs 1–20, so maybe they serve the 7 buttons.
- **Legs 21 to 28** (P2), **1 to 8** (P1) and **10 to 17** (P3).

Controller pin 1: in the photo, the notch is on the **left** side (where the "T" logo is). Seen from above,
pin 1 is the **bottom left corner**: the bottom row runs from 1 to 20 (left to right) and the top row
from 21 to 40 (right to left).

| LCD pin | Signal | Controller leg | Reading (beep / Ω) | Note |
|---|---|---|---|---|
| 4 | RS | | | |
| 5 | RW | | | (skip if 4.1 beeped) |
| 6 | E | | | |
| 7 | D0 | | | (skip if 4-bit) |
| 8 | D1 | | | (skip if 4-bit) |
| 9 | D2 | | | (skip if 4-bit) |
| 10 | D3 | | | (skip if 4-bit) |
| 11 | D4 | | | |
| 12 | D5 | | | |
| 13 | D6 | | | |
| 14 | D7 | | | |

And the I2C lines:

| 24C01 pin | Signal | Controller leg | Note |
|---|---|---|---|
| 5 | SDA | | |
| 6 | SCL | | |

If an LCD pin **does not beep with any leg**, measure resistance: it may go through a series resistor. If you still
cannot find it, follow the trace in the photo and note where it goes.

---

## 6. (Optional) Measure voltage with the amplifier on

Do this **only after** all the measurements above, and only if you feel safe. Clip the **black** probe with an
alligator clip to GND **before** switching the amplifier on. With the red probe, touch **only** the indicated point.
Multimeter on **DC voltage (V⎓, 20 V range)**.

| Point (red probe) | Expected | Result |
|---|---|---|
| LCD pin 2 (VDD) | about 5 V | |
| LCD pin 3 (VO) | 0.3 to 1.5 V | |

Unplug the amplifier from the mains before removing the clip.

---

## When you are done

Send the filled-in tables, or photos of them, along with the photos of the board. With that I will prepare:

1. The analyser **wiring plan**: which wire goes from which point on the board to which Pico pin,
   with the 1 kΩ protection resistors.
2. The **capture setup**: channels, trigger on E and frequency.
