# Capture plan: what the controller sends to the display

> **Completed on 2026-10-23.** The results are in `docs/protocol.md`. Kept as a record. The display is
> no longer connected to the controller (`docs/installation.md`).

**Goal:** record **everything** the SP103 controller sends to the LCD (at power-on, when changing input, when moving
the volume, the Function button…). With that we build the full "dictionary" of commands and texts. Then we take it
all apart, close the amplifier and move on to the bench, with the spare display.

**Nothing is cut or soldered.** The wires are only pushed onto the LCD's little pins.

Pin map and technical details: `docs/analyzer-wiring.md`.

---

## Part 0: what to gather

- [X] Pico 2 W (already with the analyser firmware) and a **data** USB cable
- [X] Mac with LogicAnalyzer (`tools/logicanalyzer/abrir.sh`), **on battery** (charger unplugged)
- [X] 830-hole breadboard
- [X] **12 female-female jumpers** of about 20 cm (11 signals + 1 GND)
- [ ] (Optional) **11 1 kΩ resistors** (brown, black, red). They are only insurance; it can be done without them,
      following the order in Part 3 strictly.
- [X] Masking tape and a pen, to label the wires
- [X] Phone to take photos of each step
- [X] Amplifier already open, with the front panel loose, as in your photos

---

## Part 1: mount the Pico on the breadboard (away from the amplifier)

1. Fit the Pico on the breadboard **straddling the centre channel**: one row of pins on each side, with the USB
   facing the end of the breadboard.
2. **Standing resistors:** for each of the 11 signals, fit a 1 kΩ resistor **standing up** in a free hole next to the
   Pico pin. The bottom leg goes in the hole; the top one points up.
   The female jumper fits onto that top leg.

   ```
        female jumper  →  goes to the LCD pin
             │
             ▓  ← top leg of the resistor
             █  1 kΩ resistor (standing)
             │
      ───────●──────────●  Pico pin (same breadboard row)
   ```

   Use the table below. Pico pins 4 to 16 are all on the same side, right after pin 3 (GND).

   | Wire label | Pico physical pin (GPIO) | Goes to LCD pin | With resistor? |
   |---|---|---|---|
   | **GND** | 3 (GND) | 1 | **no**, direct connection |
   | **E** | 4 (GP2) | 6 | yes |
   | **RS** | 5 (GP3) | 4 | yes |
   | **RW** | 6 (GP4) | 5 | yes |
   | **D0** | 7 (GP5) | 7 | yes |
   | **D1** | 9 (GP6) | 8 | yes |
   | **D2** | 10 (GP7) | 9 | yes |
   | **D3** | 11 (GP8) | 10 | yes |
   | **D4** | 12 (GP9) | 11 | yes |
   | **D5** | 14 (GP10) | 12 | yes |
   | **D6** | 15 (GP11) | 13 | yes |
   | **D7** | 16 (GP12) | 14 | yes |

   Note that Pico pins 8 and 13 are GND: they stay **unwired**.

3. **GND:** fit a female-male jumper (or a male-male joined to a female-female) in the row of Pico pin 3. This wire
   goes **directly** to LCD pin 1, with no resistor.
4. **Labels:** stick a masking tape label on the loose end of each wire (E, RS, RW, D0…D7, GND).
5. **Photo:** take a photo of the assembled breadboard.

> **Without resistors (your case):** skip step 2. Use **female-male** jumpers: the male end goes in a free breadboard
> hole, in the row of the Pico pin, and the female end goes on the LCD pin. If you only have female-female, take the
> Pico off the breadboard and fit the female end directly onto its pin.
> The Pico tolerates the 5 V **as long as it is plugged into USB before the amplifier** (Part 3). The resistors were
> only insurance in case that order fails. Without them, the order becomes **mandatory**.

---

## Part 2: connect the wires to the LCD (amp UNPLUGGED)

1. **Confirm** that the amplifier's power cord is **unplugged**.
2. **Mark pin 1:** it is the little pin at the **left end** of the LCD row, looking at the display from the front
   (the side closest to the contrast trimpot). Stick a small piece of tape on the board next to it.
3. **Count the pins** from there: 1, 2, 3… up to 16. In your photo IMG_0777, they sit in the gap between the LCD board
   and the control board.
4. **Fit the jumpers in order.** Start with **GND on pin 1**, then:

   | LCD pin | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 |
   |---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
   | Wire | **GND** | ✖ free | ✖ free | **RS** | **RW** | **E** | **D0** | **D1** | **D2** | **D3** | **D4** | **D5** | **D6** | **D7** | ✖ free | ✖ free |

   ⚠️ **Pin 2 = +5 V: never connect anything to it.**

5. **Check:**
   - [ ] Each female connector went **all the way in** and is firm (pull gently).
   - [ ] No connector touches the neighbouring pin (pin 2 especially).
   - [ ] The wires do not strain or bend the little pins. Tape the bundle to the table if needed.
   - [ ] The breadboard with the Pico rests **outside the amplifier**, on cardboard or wood, not touching the chassis.
6. **Photo:** take a photo of the wires fitted on the LCD.

---

## Part 3: power up in the right order

**Always in this order:**

0. **Keep the Mac from sleeping** (if it sleeps, it may cut USB power while the amp is on).
   Open a terminal and run the command below. Leave that window open during all the captures; to stop it, press
   Ctrl+C.
   ```
   caffeinate -dis
   ```
   Also tape down the USB cable, so it does not get pulled by accident.
1. Plug the **Pico into the Mac's USB**.
2. Open the program: `tools/logicanalyzer/abrir.sh`.
3. Choose `/dev/cu.usbmodem…` (or `tty.usbmodem…`) and click **Open device**.
   `LOGIC_ANALYZER_PICO_2_V6_0` should appear.
4. **Only now** plug the amplifier into the mains. Its screen should light up normally, because the wires only
   "listen" and change nothing.

If the amplifier's screen looks odd (blank or with garbage): unplug the amp and check the wires.

---

## Part 4: set up the capture (once only)

Click **Capture** and set:

- **Channels:** tick **Channel 1 to Channel 11**. In the fields below each one, type the names:
  `E, RS, RW, D0, D1, D2, D3, D4, D5, D6, D7`. The script uses these names.
- **Presamples:** 512
- **Postsamples:** the **maximum** the program accepts (about 190000). If it gives an error, lower it until it is
  accepted.
- **Edge trigger:** channel **01** (E), with **Negative edge UNTICKED**.
  ⚠️ In this firmware the "edge trigger" actually fires on **level**: unticked, it fires when E is at **1**. Since E
  sits at 0 when idle, the capture waits for the first pulse. With "Negative edge" ticked, it would fire **right away**
  (E is already at 0), before you do anything. That is what happened in the first test (`captures/volume.lac`).
- **Frequency:** depends on the capture (see the table in Part 5).

The program remembers these settings next time. After that, just change the frequency when the table asks for it.

**How each capture works:**
1. Click **Capture → Accept**. The program sits **waiting**.
2. Do the action on the amplifier (press the button, turn the knob…).
3. The capture fires by itself on the first E pulse and shows up on screen.
4. Save with **File → Save** in the `captures/` folder, with the name from the table.

If nothing happens in about 10 seconds, click **Abort**. That is also information: write it down.

**Did it fire the instant you clicked Accept, before you touched anything?** Then the trigger is wrong (check that
"Negative edge" is unticked) or the controller was writing by itself. Test by clicking Accept and waiting, without
touching the amp.

---

## Part 5: the captures

Do them in order. **Capture 1 decides the frequency of the others.**

| # | File | Frequency | Action on the amplifier | What it answers |
|---|---|---|---|---|
| 1 | `01-pulso-e.lac` | 25 MHz | Turn the volume one "click" | the E pulse width, to choose the frequency of the next ones |
| 2 | `02-parado.lac` | F | **Do not touch anything** for 10 s (Abort if it does not fire) | does the controller redraw the screen by itself? |
| 3 | `03-liga.lac` | F | With the capture waiting, **plug the amp into the mains**. Before that, unplug it; the Pico stays on USB | power-on sequence |
| 4 | `04-phono.lac` | F | Press **Phono** | input text |
| 5 | `05-tuner.lac` | F | Press **Tuner** | |
| 6 | `06-tape.lac` | F | Press **Tape/Aux** | |
| 7 | `07-cd.lac` | F | Press **CD** | |
| 8 | `08-dvd.lac` | F | Press **DVD** | |
| 9 | `09-dab.lac` | F | Press **DAB** | |
| 10 | `10-vol-sobe.lac` | F | Turn the volume **up** one click | how the volume is written |
| 11 | `11-vol-desce.lac` | F | Turn the volume **down** one click | |
| 12 | `12-vol-rapido.lac` | F | Turn the volume **fast**, several clicks | does it redraw on every click? |
| 13 | `13-function-1.lac` | F | Press **Function** once | menus (bass, treble, balance?) |
| 14 | `14-function-2.lac` … | F | Press **Function** again, one capture per press, until back to the normal screen | all the menus |
| 15 | `15-function-ajuste.lac` | F | Inside a Function menu, turn the knob | how the menu values are written |
| 16 | `16-controle.lac` | F | (if you have the remote) press a button on the remote | |
| 17 | `17-desliga.lac` | F | With the capture waiting, **unplug the amp from the mains** | what is written at power-off (if anything) |

**How to choose F** (after capture 1): run the script on it (Part 6) and look at the line "E pulse width: min …".

| Shortest E pulse | F |
|---|---|
| 1.5 µs or more | 2 MHz (captures about 98 ms) |
| 0.75 to 1.5 µs | 4 MHz (about 49 ms) |
| less than 0.75 µs | 10 MHz (about 19 ms) |

If you do not want to wait for the script, use **4 MHz**: it is the most likely value.

**Capture cut off in the middle?** If the screen rebuilt by the script is incomplete, the capture ended before the
controller finished writing. Repeat the same action at a lower frequency (for example, 2 MHz).

---

## Part 6: run the script

In the terminal, in the project folder:

```
python3 tools/hd44780_decode.py captures/01-pulso-e.lac
```

To save the result of all captures at once:

```
for f in captures/*.lac; do python3 tools/hd44780_decode.py "$f" > "${f%.lac}.txt"; done
```

Or just let me know the captures are in the folder: I will run the script on all of them and build the dictionary.

---

## Part 7: take it apart and close up

1. **First** unplug the amplifier **from the mains**.
2. Click **Close device** in the program and unplug the Pico's USB.
3. Remove the jumpers from the LCD **one by one**, pulling straight, without bending the little pins.
4. Check with a photo that no little pin got bent.
5. Put the front panel back and close the amplifier.
6. Switch on and check that everything works as before.

---

## What comes next: the bench

With the dictionary ready, we build on the breadboard, **outside the amplifier**:

1. **Pico 2 W + spare display (1602):** the Pico plays the controller and reproduces the captured sequences exactly.
   If the spare display shows "Volume -26.25 dB / PHONO", we understood everything correctly.
2. **Rewrite layer:** the same Pico swaps the texts ("PHONO" → "Turntable") and tests custom messages.
3. **Decide the final install:** cut only E or all 11 pins, based on what the captures showed about the wires'
   **idle state** (the script shows this at the start of each result).
