# T9311DP leg map

Multimeter measurements. Photos: [`placa-frontal-baixo-mapa.jpg`](placa-frontal-baixo-mapa.jpg) (underside, annotated),
[`placa-frontal-mapa.jpg`](placa-frontal-mapa.jpg) (top side, annotated), [`foto-chip-encoder-J2.jpg`](foto-chip-encoder-J2.jpg)
and [`foto-receptor-IR.jpg`](foto-receptor-IR.jpg).

**Old label on the underside photo:** it says "A, common, B" on the encoder, but the common is the bottom pin (E3), as
the encoder table below shows.

## Safety rules

- Measure with the amp unplugged for 5 minutes, with less than 0.5 V between display pins 1 and 2.
- Front board only: never the mains board, the transformer or the power board.
- Never touch the 12 MHz crystal or legs 18 and 19 with the amp on.
- The board's signals are 5 V; the Pico is 3.3 V. See `../proxy-ligacao.md`.

## Leg numbering (2026-11-05)

Confirmed. Seen from above, with the LCD on the left:

| Leg | Position | Measurement | Result |
|---|---|---|---|
| 20 | last on the right, bottom row | × display pin 1 (GND) | beeps |
| 40 | first on the left, top row | × display pin 2 (+5 V) | beeps |

## IR receiver (2026-11-05)

Seen from above, with the LCD on the left and the buttons towards the viewer:

| Point | Function | Measurement | Result |
|---|---|---|---|
| Left leg | Signal | × chip leg 12 | beeps (direct connection) |
| Middle leg | GND | × GND | beeps |
| Right leg | Supply | × C903 | beeps |
| Right leg | Supply | × leg 40 (+5 V) | about 10 Ω |
| Case | GND | × display pin 1 | beeps |
| C902, top terminal | GND | × IR middle leg | beeps |
| C902, top terminal | GND | × IR left leg | no beep |
| C902, bottom terminal | Signal | × IR middle leg | no beep |
| C902, bottom terminal | Signal | × IR left leg | beeps |

The 10 Ω comes from 10.5 Ω measured on the 200 range, minus 0.6 Ω for the multimeter leads.

**Conclusions:**

- The IR receiver output goes straight to chip leg 12. No other leg beeped among legs 1–8, 13–17 and 21–27.
- C902 (33 pF) sits between signal and GND.
- If the chip is an 8051, leg 12 is P3.2/INT0, the interrupt input. The chip family has not been confirmed yet.

**IR line strength (2026-11-06):** in Ω, 200k range, amp unplugged, between the left leg (signal) and the right leg (supply): 39.0 kΩ with the red probe on the signal and 41.1 kΩ with the probes swapped. Almost the same both ways, so it is a resistor of about 40 kΩ holding the line at 1. Pulling the line to GND costs about 0.1 mA.

**Open:**

- Confirm whether the resistor of about 10 Ω is really R903.

## Volume encoder (2026-11-05)

Pins seen from below, with the LCD end facing up: E1 is the top one, E2 the middle one and E3 the bottom one.

| Point | Function | Connects to | Resistor to +5 V (leg 40) |
|---|---|---|---|
| E1 | A or B | **Chip leg 22**, direct | 4.6 kΩ |
| E2 | A or B | **Chip leg 21**, direct | 4.6 kΩ |
| E3 | Common | GND (beeps in every position) | 4.76 kΩ (this is the reading between +5 V and GND) |
| 2 mounting tabs | Mounting only | Do not beep with GND | not measured |

Continuity check: E1 × 22 and E2 × 21 beep; E1 × 21 and E2 × 22 do not beep. The same connections in Ω were noted as "nothing" and should be 0.00, since they beep.

**Conclusions:**

- C908 sits between E2 and GND.
- E1 and E2 have a resistor of about 4.6 kΩ to +5 V, and the encoder contact pulls them to GND.
- The 9.2 kΩ readings are two of these resistors in series, going through +5 V. They are not direct connections.
- If the chip is an 8051, legs 21 and 22 are P2.0 and P2.1. The chip family has not been confirmed yet.
- In the first sweep, 21 and 22 did not beep, and one E2 reading failed for lack of contact. Pressing firmly makes a difference.

**Open:**

- Which of the two is A and which is B: this depends on the direction of rotation.
- Where C907 connects: it did not beep with E1, E2, E3 or GND.
- Why E1 reads 6.9 kΩ to legs 1, 2 and 3, and 9.2 kΩ to legs 4–8, 13–17, 23–27. Come back to this when measuring the buttons.

## Buttons (2026-11-05)

Leads seen from above: P1 and P3 on the left, P2 and P4 on the right. P1 beeps with P3, and P2 beeps with P4. When not pressed, one side does not beep with the other.

| Button | P1 (left) | P2 (right) |
|---|---|---|
| K1 | Leg 13 | Leg 8 |
| K2 | Leg 14 | Leg 8 |
| K3 | Leg 13 | Leg 7 |
| K4 | Leg 14 | Leg 7 |
| K5 | Leg 13 | Leg 5 |
| K6 | Leg 14 | Leg 5 |
| K7 | Leg 6 | Leg 13 |

On buttons K2 to K7, measuring stopped at the first beep. On K1, the list was gone through to the end. K7 has its sides swapped relative to the others.

The matrix, with the legs each button connects:

| | Leg 8 | Leg 7 | Leg 6 | Leg 5 |
|---|---|---|---|---|
| **Leg 13** | K1 | K3 | K7 | K5 |
| **Leg 14** | K2 | K4 | free | K6 |

**Conclusions:**

- The buttons form a 2 × 4 matrix. No K1 lead goes to GND.
- With the multimeter it is not possible to tell which legs the chip drives and which it reads. That will come from the capture.

The power button is a switch that goes straight to the power supply board (220 V). It is not part of the matrix and **must not be measured**.

**Open:**

- The 14 × 6 crossing is free: none of the buttons K1–K7 uses it.

## EEPROM IC801 (2026-11-05)

| IC801 pin | Function (24C01) | Connects to |
|---|---|---|
| 1, 2, 3 | Address | GND |
| 4 | GND | GND |
| 5 | SDA | **Chip leg 25** |
| 6 | SCL | **Chip leg 24** |
| 7 | Write protect | GND |

With the address pins on GND, the expected address is 0x50. With pin 7 on GND, writing is enabled. The capture will confirm both.

## Cable to the input board (2026-11-05, in progress)

On the board, there are 4 wires between the display board and the RCA input board, not 9 as the brief says. Still to confirm which connector they arrive at. Suspicion: they are the 4 signals of CON51 (SDA0, SDA1, SCL and GND).

Looking at the board from the front, the wires are F1 to F4, left to right.

| Wire | Function | Connects to |
|---|---|---|
| F1 | GND | GND (beeps) |
| F2 | Signal, probably I2C | Chip leg 1 |
| F3 | Signal, probably I2C | Chip leg 2 |
| F4 | Signal, probably I2C | Chip leg 3 |

**Conclusions (to be confirmed):**

- CON51 has SCL and two SDA lines. The order GND, CL, DA1, DA0 suggests F2 = SCL, F3 = SDA1 and F4 = SDA0, but only the capture will tell.
- Legs 1, 2 and 3 are not the EEPROM ones (24 and 25). The PT2314s seem to be on another bus, so their capture should be on F2–F4, not on IC801.
- F2, F3 and F4 read 4.6 kΩ to leg 40 (20k range), the same as E1 and E2. The hypothesis of extra resistors (2.3 kΩ) was ruled out.
- E1's 6.9 kΩ to legs 1, 2 and 3 remains unexplained. 9.2 kΩ would be expected.

There is also an 8-wire cable between the display board and the amp board. Still to confirm which connector it arrives at. Before measuring continuity on it, check the voltage, because the amp board may hold a charge. Measure on the display board only.

Voltage on the 8 wires to GND, with the amp unplugged: 0 V on all of them. Looking at the board from the front, the wires are G1 to G8, left to right.

| Wire | Function | Connects to |
|---|---|---|
| G1 | Q902 output | Q902 leg closest to the edge |
| G2 | GND | GND |
| G3 | Controller signal | **Chip leg 16** |
| G4 | +5 V | Leg 40 |
| G5 | GND | GND |
| G6 | Unknown | No tested leg beeped |
| G7 | Unknown | No tested leg beeped |
| G8 | Unknown | No tested leg beeped |

Legs tested on G1, G3, G6, G7 and G8: 4, 15–17, 23, 26, 27 and 29–31.

Q902, seen from above with the LCD on the left: Q1 is the left leg, Q2 the middle one and Q3 the right one. On continuity, none of the three beeps with GND (the answer for G1, G6, G7 and G8 is still missing).

Q2 in Ω (20k range):

| Chip leg | Reading | Likely interpretation |
|---|---|---|
| 15 | 4.66 kΩ | 4.7 kΩ base resistor: Q2 connects to leg 15 |
| 4, 16, 17, 23, 26, 27 | 13.92 kΩ | 4.66 + 4.6 + 4.6 kΩ, through leg 15 and +5 V |
| 31 | 9.30 kΩ | 4.66 + 4.6 kΩ: leg 31 is on +5 V |
| 29, 30 | no reading | Not connected to these points |

The original message said "37"; the requested measurement was leg 27.

**Conclusions:**

- Leg 15 drives the base of Q902 through a resistor of about 4.7 kΩ.
- The Q902 leg closest to the board edge beeps with G1. The leg farthest from the edge beeps with G4 (+5 V). The middle one is Q2, the base.
- With the usual 2N4401 pinout, the +5 V leg is the collector and the G1 leg is the emitter. So when leg 15 goes high, Q902 should put about 4.3 V on wire G1, which goes to the amp board. Still to confirm with the amp on.
- Leg 31 on +5 V and legs 29 and 30 unconnected match an 8051 (EA high; PSEN and ALE unused). It is a good hint, not proof.

**Open:** what G3 does, and whether any of the wires G1, G6, G7 and G8 goes through Q902 or carries audio.

## Front LED (2026-11-05)

The LED has 3 legs: L1 (left), L2 (middle) and L3 (right). None beeps with GND.

| Leg | Beeps with | Likely function |
|---|---|---|
| L1 | Nothing | One of the colours |
| L2 | Leg 40, leg 31 and G4 | Common, on +5 V |
| L3 | Nothing | One of the colours |

Three legs with the middle one on +5 V suggest a two-colour common-anode LED. L2 beeping with leg 31 confirms that leg 31 is on +5 V.

In Ω (20k range):

| LED leg | Chip leg | Reading | Likely interpretation |
|---|---|---|---|
| L1 | 26 | 0.99 kΩ | Resistor of about 1 kΩ: L1 connects to leg 26 |
| L1 | 4, 17, 23, 27 | 10.25 kΩ | 0.99 + 4.6 + 4.6 kΩ, through +5 V |
| L3 | 27 | 0.45 kΩ | Resistor of about 470 Ω: L3 connects to leg 27 |
| L3 | 4, 17, 23, 26 | about 9.7 kΩ | 0.45 + 4.6 + 4.6 kΩ, through +5 V |

Observed with the amp on: **red in standby, green when on**. Turning the volume does not change the colour. Still to measure which leg lights each colour (L1/leg 26 or L3/leg 27).

## Transistor Q901 (2026-11-05)

Seen from above, with the LCD on the left: T1 is the left leg, T2 the middle one and T3 the right one.

| Leg | Beeps with | Likely function |
|---|---|---|
| T1 | Leg 4, through about 470 Ω (0.46 kΩ) | Base, to be confirmed |
| T2 | Display pin 15 (backlight) | Output to the backlight |
| T3 | Leg 40 and G4 (+5 V) | +5 V input |

Q901 looks like the LCD backlight switch, driven by leg 4. T1 × legs 17 and 23 read 9.69 and 9.66 kΩ, which are 0.46 + 4.6 + 4.6 kΩ through +5 V. Still to confirm with the amp on whether leg 4 changes between standby and on.

## To recheck (2026-11-05)

The leg count may have been off in the measurements made before the K1–K7 buttons, which are correct. To be rechecked, using legs 13, 20 and 21 as reference:

- [x] IR, signal → leg 12: confirmed (beeps on 12; does not beep on 11 or 13)
- [x] Encoder, E1 → leg 22 and E2 → leg 21: count confirmed
- [x] E1 Ω readings to legs 1, 2 and 3 (6.9 kΩ): count confirmed

## In use (2026-11-06)

The Pico inside the amp uses these points: the IR signal (GP15), the encoder's E1 (GP14) and legs 6 and 13 of the
Function button, which is K7 (GP0 and GP1). See `../proxy-ligacao.md`. The PT2314 captures were dropped from the plan,
because the volume already comes from the display.

**Function (2026-11-06):** with the button released, leg 6 pulses and leg 13 stays at 1. With it pressed, leg 13 drops
together with leg 6 on every pulse. The leg 6 pulses come in groups of 3, about 30 µs each, every 320 µs.

## Still to measure

- [ ] C907: find where it connects
- [ ] G6, G7 and G8: find where they go
- [ ] Legs 17 and 23: function still unknown
