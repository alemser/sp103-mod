# How the Pico can change the amp's display text (interception options)

**Decided and done on 2026-10-29: option 3b, display desoldered at pins 4–14, with the Pico as proxy.** Install:
`proxy-ligacao.md`.

This document sums up why the Pico has to sit in the middle, the options considered and what the "no cut" attempt
(2026-10-24 to 10-28) taught. The code and tests of that attempt (`escrita.py`, `plano.py`, `refresh.py`,
`tools/planejador.py` and the writing `tools/teste_*_pico.py`) are in the git history, up to commit `6be4eb2`.

## Why "overwrite in parallel" does not work

The idea was to leave everything connected as it was and have the Pico rewrite the display right after the
controller. That is not possible, for electrical reasons:

- **E (leg 28, P2.7):** when idle, the controller holds E at 0 strongly. If the Pico raised E, the two would fight over
  the wire.
- **Data (legs 32–39, P0):** when idle, they stay latched at the last byte written. Bits at 0 are held strongly by the
  controller; the 4.7 kΩ resistors (R907/R908) only pull the bits at 1 up to 5 V. The Pico can pull a line down, but
  not up.

There is no window in which the Pico can write on its own without fighting the controller.

## What the photos showed

| Photo | What it shows |
|---|---|
| ![controller](img/minha-placa/controlador-t9311-sem-soquete.jpg) | The T9311 is **soldered straight to the board, with no socket** |
| ![side](img/minha-placa/lcd-pinos-lateral.jpg) | The display is held by a 16-pin header, soldered to both boards, with a **plastic spacer** between them. The pin ends stick out above the display board |
| ![solder](img/minha-placa/lcd-lado-solda-trilhas.jpg) | On the solder side, **one trace leaves each pin**, separate right after the solder joint. Further on they merge into a thin bundle to the controller |

## Options

| # | Option | Verdict |
|---|---|---|
| 1 | Adapter in place of the controller (40-pin "sandwich" socket) | Discarded: the chip is soldered; 40 legs would have to be desoldered |
| 2 | Cut 11 traces on the solder side, right after the display pins | Possible, without touching the display; risk of cutting a neighbouring trace |
| 3a | Cut the pins between the boards | Not feasible: the plastic spacer keeps the cutters from getting in |
| 3b | Desolder the display and resolder only pins 1–3, 15 and 16; holes 4–14 take the controller-side wires | **Chosen and done (2026-10-29)** |
| — | "No cut" writing: the Pico only pulls wires to 0 during the controller's transactions | Tested and retired (below) |

With 3b, each of the 11 signals gets two sides:
- **Controller → Pico**: the 11 wires (RS, RW, E, D0–D7) on GP2–GP12. The Pico pretends to be the display and answers
  "free" to the busy flag reads; without an answer, the controller keeps asking forever.
- **Pico → display**: only 6 wires (RS, E, D4–D7) on GP16–21, 4-bit mode, with the display's RW on GND. The display
  never sends a signal back, so no 5 V reaches the Pico on this side.
- **To go back to the original**: 11 jumpers connecting each controller wire to the display wire.

## The no-cut attempt (2026-10-24 to 10-28)

The Pico sat in parallel, with the display connected to the controller, and only pulled wires to 0. All four tricks
worked on the amp:

| Trick | How |
|---|---|
| Change bits of a letter | clear bits of the character the controller sends ("PHONO" → "PHONE") |
| Custom glyphs | at power-on, clear dots in the bar glyphs (CGRAM) so they become letters |
| Move letters | on a busy flag read, pull RW: the LCD receives a "go to..." command with the bits of the last byte |
| Freeze cells | turn a write into command 0x00, which the LCD ignores |

But the Pico can only **clear bits** of the bytes the controller already sends. So:

- Only short, carefully chosen names came out (REGA, TAPE). Names like "Rega Planar 2" were impossible.
- The name only appeared from the second redraw of an input on: on the first press, at power-on and after the Function
  menu, the original name appeared.
- DAB and DVD only differ in the second letter. There was no safe plan for DAB → "Air", and quick switches produced
  mixed-up screens (`TUGE`, `TEGA`).

With the proxy, none of these limits exist: any text up to 16 characters, from the first screen.

### What was learned

The facts about the controller are in `descobertas-protocolo.md` ("Port electrics and busy flag reads"): RS and RW are
weak at 1, E and the data at 0 are strong, the controller releases only D7 to read the busy flag and asks again if it
reads "busy", and the LCD ignores command 0x00.

PIO pitfalls in MicroPython, which cost attempts and apply to any new program:

| Pitfall | How to avoid it |
|---|---|
| `mov(pindirs, ...)` generates the same code as `mov(exec, ...)`: the PIO executes the value as an instruction | change pin direction only with `out(pindirs, n)` or `set(pindirs, n)` |
| Inside an `@rp2.asm_pio` function, the module's variables do not exist (`NameError`) | write the numbers directly (for example, `wait(1, gpio, 2)`) |
| `autopull=True` makes `pull()` do nothing if the OSR is full | no autopull; `pull(ifempty)` when needed |
| The default is `out_shiftdir=SHIFT_LEFT`: `out()` takes the bits from the top of the OSR | `out_shiftdir=SHIFT_RIGHT` when the mask is in the low bits |
| Noise on E with long wires: false pulses of up to ~1 µs | accept a pulse only after 3 µs at 1 (the `sniffer.py` filter) |
| Each PIO block has only 32 instructions | the sniffer sits on PIO0; `busy.py`, on PIO1 |
| `Pin(n, Pin.IN)` takes the pin away from the PIO | create the `Sniffer` before the `busy.py` `Responder` |
