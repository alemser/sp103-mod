# sp103-mod

Custom text on the front display of the **Acoustic Solutions SP103** amplifier, with a **Raspberry Pi Pico 2 W**
sitting between the original controller (T9311) and the display (16x2 LCD, HD44780).

The repository was called `sp103-display-proxy` until 2026-11-16, when it was renamed `sp103-mod`.

- The controller and the amp's functions stay original. The Pico changes what the display shows: "TUNER" becomes
  "Rega Planar 2", and so on.
- The Pico publishes the amp's state (volume, input, menus) on the network, at `http://sp103.local/` (API only: `docs/api-estado.md`).
- Optional: the two lines become a VU meter (L and R channels, with peak hold) while music plays, using data from the
  groove-detector (`docs/vu.md`).
- The Pico controls the amp over Wi-Fi: it sends the remote control codes straight onto the IR line, inside the amp, and presses
  the Function button. With the amp in standby, turning the volume knob turns the amp on (`docs/proxy-ligacao.md`).
- The remote control keeps working, and groove-rig still controls the amp through the Broadlink.
- The display no longer shows a clock in standby: the standby clock was removed on 2026-11-16.

## How it works

```
T9311 controller ──(GP2–GP12, 8 bits)──► Pico 2 W ──(GP16–21, 4 bits)──► amp display
                  ◄── "not busy" on D7 ──┘
IR receiver ◄──────(GP15, pulls to 0 only)── Pico 2 W
volume knob ───────(GP14, read only)──────► Pico 2 W
Function button ◄──(GP0 reads, GP1 pulls to 0 only)── Pico 2 W
```

1. The display was desoldered at pins 4–14 (2026-10-29). Now the controller talks only to the Pico.
2. The Pico reads every byte the controller sends (`firmware/sniffer.py`, PIO + DMA) and answers "not busy" to the
   "busy?" queries (`firmware/busy.py`). To do that it only pulls D7 to 0, never drives 1.
3. The Pico rebuilds the screen (`firmware/hd44780.py`), swaps the names (`firmware/names.py`) and draws on the display
   (`firmware/lcd1602.py`). The main program is `firmware/proxy.py`.
4. To control the amp, the Pico pulls the IR line to 0 with the same timing as the remote control (`firmware/ir.py`) and
   imitates the Function button (`firmware/panel.py`). `firmware/control.py` combines the two for direct settings.
5. The Pico is powered by the amp itself (5 V from display pin 2, also in standby) and updated over Wi-Fi.

## Usage

| What for | How |
|---|---|
| See the amp's state | the Amp Link app (amp-link repository), Now tab |
| Change the input names and the start screens | the app, Names tab (up to 16 characters, no accents) |
| Turn on the VU meter | the app, Display tab (`docs/vu.md`) |
| Control the amp | the app, Now tab, or `curl -X POST "http://sp103.local/control?target=bass&dir=up"` (`docs/api-estado.md`) |
| See the bus | the app, Status tab |
| Download the log | `curl http://sp103.local/bus.csv` |
| Set up or change the Wi-Fi network | no cable: join the Pico's `AmpLink-SP103-XXXX` network (password `amplink-setup`) and open `http://192.168.4.1/` (`docs/wifi.md`) |
| Update the Pico's program | `python3 tools/enviar.py` |
| Test on the computer | `python3 tools/test_proxy.py` (and the other `tools/test_*.py`); the bridge: `cd relay && make test` |

## Documents

| Document | Contents |
|---|---|
| [`docs/proxy-ligacao.md`](docs/proxy-ligacao.md) | **The current installation**: wiring, power, safety rules, troubleshooting |
| [`docs/api-estado.md`](docs/api-estado.md) | The contract for `/state`, `/events` and the `/control` and `/ir` routes (amp state and commands) |
| [`docs/vu.md`](docs/vu.md) | The VU meter: the bridge, the protocol, what the display shows, the settings |
| [`docs/trocar-de-placa.md`](docs/trocar-de-placa.md) | **Installing the bridge** on a board: do it when moving the capture to another board or flashing a new image |
| [`docs/atualizacao-wifi.md`](docs/atualizacao-wifi.md) | Updating the Pico over Wi-Fi, with automatic rollback |
| [`docs/wifi.md`](docs/wifi.md) | Setting up the Pico's Wi-Fi without a cable (its own network) and finding the Pico on the network without a fixed IP |
| [`docs/descobertas-protocolo.md`](docs/descobertas-protocolo.md) | How the controller talks to the display: commands, screens and the electrical side |
| [`docs/bancada-ligacao.md`](docs/bancada-ligacao.md) | Spare display on the bench (same 4-bit wiring as the amp's display) |
| [`docs/ligacao-analisador.md`](docs/ligacao-analisador.md) | Pin map of the LCD and the T9311, logic analyser wiring |
| [`docs/placa-frontal/mapa-pernas.md`](docs/placa-frontal/mapa-pernas.md) | Pin map of the T9311DP controller, measured with the multimeter, and photos of the board |
| [`docs/historico/`](docs/historico/) | Project record: initial goal, options considered, and measurement and capture plans. They do not describe the current state |

## Folders

- `firmware/`: the Pico's program (MicroPython). `main.py` and `secrets.py` only go over the cable; the Wi-Fi network lives in
  `wifi.json`, written through the Pico's setup network.
- `relay/`: the VU bridge (`sp103-vu-relay`, Go), which runs on the board with the groove-detector.
- `tools/`: Wi-Fi upload, tests on the computer, log reader and capture decoder.
- `captures/`: logic analyser `.lac` captures, used by the tests.
- `docs/`: documentation and photos of the board.
