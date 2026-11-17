# Amp state and command API (for groove-rig and other clients)

The Pico publishes what the SP103 display shows, already interpreted, at `http://sp103.local/` (or the Pico's IP,
192.168.178.108). The state is read-only; commands to the amp live on the `/control` and `/ir` routes. This is the contract
groove-rig (the amplifier's "state provider") can rely on; changes to it must also change the clients.

## Routes

| Route | What |
|---|---|
| `GET /device` | Who the bridge is and what it can do: the DeviceLink contract `api` 2 (`docs/contract-v2.md`, in the amp-link repository) since 2026-11-17, with the state fields, the remote and the settings (`firmware/device.py`) |
| `GET /settings`, `PATCH /settings` | The person-editable configuration (input names, boot screens, VU, info screens) as flat ids, `{"inputs.TUNER": "Rega Planar 2", "vu.on": true, ...}`. `PATCH` takes only what changes; a refusal is `400 {"error", "id"}` (`firmware/settings.py`) |
| `GET /names`, `PUT /names` | The same configuration as one object, as in contract v1 (`PUT` replaces it all), plus the bridge's counters; kept for curl and older apps |
| `GET /state` | The current state, as JSON |
| `GET /events` | Server-Sent Events: one `data: {json}` with the current state right on connect, and another on every change. At most 4 states a second, always the latest. A `: ping` comment every 1 s keeps the connection alive: with nothing for about 5 s, the client should reconnect |
| `GET /ir` | Accepted commands, sends made, and readings of the IR line and the volume knob |
| `POST /ir/send?cmd=volume_up` | Sends a command to the amp over the IR line |
| `POST /control?target=bass&dir=up` | Adjusts the amp directly, without the client dealing with menus (see "Direct settings") |
| `/wifi` | The Pico's Wi-Fi network and cable-free setup (`docs/wifi.md`). To find the Pico without a fixed IP: UDP broadcast `DEVICELINK?` (or `AMPLINK?`) on port 47800 |

The JSON from `/state` and `/events` is the same. Example:

```json
{"power": "on", "volume_db": -20.0, "input": "DAB", "input_id": "dab", "input_name": "AirPlay/BT - DAC",
 "bass_db": 2, "treble_db": 0, "balance": {"side": "L", "db": -5.0}, "loudness": false, "speakers": true,
 "screen": "normal", "firmware": "1.0", "lcd": ["Volume -20.00 dB", "DAB             "],
 "updated_at": 3747990, "version": 5}
```

## Fields

`null` in any field = not known yet. The Pico only knows a value after the amp shows it on the display: after
the Pico restarts, bass stays `null` until someone changes it.

| Field | Values | Notes |
|---|---|---|
| `power` | `"on"`, `"standby"`, `null` | `"on"`: the amp showed a known screen. `"standby"`: the controller blanked the screen (see below). `null`: the Pico started and the amp has not shown anything yet |
| `volume_db` | −78.75 to 0, steps of 1.25 | The number on the volume screen |
| `input` | `PHONO`, `TUNER`, `TAPE/AUX`, `CD`, `DVD`, `DAB` | The original name on the amp |
| `input_id` | `phono`, `tuner`, `tape_aux`, `cd`, `dvd`, `dab` | Stable, for programs; the same ids as groove-rig's `acoustic_solutions_sp103` profile |
| `input_name` | text | The custom name (app), or the original |
| `bass_db`, `treble_db` | −14 to 14, integers | |
| `balance` | `{"side": "L"/"R"/null, "db": −78.75..0}` | `db` 0 = centre. `side` null below 5 dB: the amp's bar does not show the side yet |
| `loudness`, `speakers` | `true`, `false` | When leaving standby, the amp always comes back with `speakers` on, and the Pico already shows `true`. `loudness` stays as it was (measured on 2026-11-06) |
| `screen` | `normal`, `volume`, `bass`, `treble`, `balance`, `loudness`, `speakers`, `boot`, `about`, `standby`, `unknown` | The screen the amp is showing. `bass`/`treble`: the amp is in the mode where Volume ± changes the tone (up to 6 s after the last key) |
| `firmware` | text | From the "SW version" screen |
| `lcd` | 2 strings of 16 | The controller's original lines (the bar block becomes `■`) |
| `updated_at` | ms | The Pico's internal clock at the last change. Only useful for comparing with another `updated_at` |
| `version` | integer | Increases on every change. Goes back to 0 when the Pico restarts |

## Standby

When going to standby, the controller writes spaces on both lines and stops; `power` becomes `"standby"` and so does
`screen`. When leaving standby, it draws the normal screen straight away (volume and input), and `power` becomes `"on"`. Only when the
amp gets power from the wall socket does it clear the screen ("Clear display") and show "ACOUSTIC SOLUTIONS". Confirmed on the amp on
2026-10-29: standby → `"standby"` in 0.1 s; power on → `"on"`. The other fields keep their last value during standby (the amp comes back with the same volume and the same input).

The Pico is powered by the amp in standby too. If it restarts with the amp in standby, `power` stays `null` until the amp
is turned on: a client that needs to know must treat `null` as "don't know", never as off.

## For the client

- Prefer `/events`: each change arrives right away (about 10 ms after the controller finishes the screen, plus Wi-Fi).
- If the Pico disappears (no `ping` for about 5 s), consider the state unknown and reconnect with increasing backoff.
- The Pico serves few connections at a time: one `/events` per client, not one per screen. It keeps one connection per IP
  and 3 in total: a new connection from the same IP drops the old one, and when the limit is reached the oldest goes.
- `sp103.local` works on iOS and macOS. groove-rig (Go without cgo) does **not** resolve `.local` names: use the IP,
  which is fixed by the router (`http://192.168.178.108/events`).
- In groove-rig, this is the SP103 profile's "state provider": the generic contract is in its `docs/state-provider.md`.

## Direct settings

The client asks for the result, and the Pico does the clicks (`firmware/control.py`). The response is the state after the change, or
`400` with `{"error": "..."}`. Only one request at a time and, except for `target=key`, only with `power` = `on`.

| Request | What the Pico does |
|---|---|
| `target=volume&dir=up` or `down` | Waits for an open menu to close and sends volume. The first press only opens the volume screen, so it checks the value and repeats |
| `target=bass` or `treble`, with `dir` | Sends the dedicated key and then volume. 2 dB per step |
| `target=balance`, with `dir` | Clicks Function until Balance and sends volume. 1.25 dB per step |
| `target=loudness&on=1` or `0` | Clicks Function until Loudness and sends volume + (on) or − (off) |
| `target=speakers&on=1` or `0` | The same, on Speakers |
| `target=key&name=<command>` | Sends a remote control key, such as `power_toggle` or `select_cd`. Also works in standby |

All were tested on the amp on 2026-11-06. In about 1 click in 8, Function also switches the input to PHONO;
the Pico notices and restores the previous input in about 1 s. If it does not know the input yet, right after restarting,
it cannot restore it.

## Commands

`POST /ir/send?cmd=<command>` sends the command and responds like `GET /ir`. Unknown command or another send in
progress: `400` with `{"error": "..."}`. A send takes about 130 ms.

| Command | Effect |
|---|---|
| `power_toggle` | Turns on or puts into standby. It is the same command for both: check `power` first |
| `volume_up`, `volume_down` | The first press only opens the volume screen; the following ones change 1.25 dB each |
| `bass`, `treble` | Open the setting; for 6 s, `volume_up` and `volume_down` change that value |
| `select_phono`, `select_tuner`, `select_tape_aux`, `select_cd`, `select_dvd`, `select_dab` | Switch the input |

Tested on the amp: `power_toggle`, volume, `bass`, `treble`, `select_cd` and `select_dvd`. The other inputs have their bits
checked against the groove-rig profile.

`GET /ir`:

```json
{"commands": ["power_toggle", "volume_up"], "sending": false, "sent": 3, "line": 1, "knob": 1, "knob_edges": 6,
 "wakes": 1}
```

| Field | Meaning |
|---|---|
| `commands` | The accepted commands |
| `sending` | A send is in progress |
| `sent` | Sends since the Pico started, including those from the volume knob |
| `line` | IR line level. At rest, 1 |
| `knob`, `knob_edges` | Level of the encoder's E1 and changes counted since the Pico started |
| `wakes` | Times turning the knob turned the amp on |
