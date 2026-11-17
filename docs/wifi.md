# Pico Wi-Fi: set up without a cable and find without an IP

The Pico keeps the home network in `wifi.json` and is set up through its own Wi-Fi network, without a USB cable. The app finds the Pico
on the network by itself, with no IP typed in. The program lives in `firmware/wifi.py`; the tests, in `tools/test_wifi.py`.

Decided on 2026-11-08, after testing both approaches on the bench:

- **Bluetooth, like Oceano: rejected.** Android asks for pairing, but it never completes: the official MicroPython
  for the Pico 2 W ships with pairing disabled (`MICROPY_PY_BLUETOOTH_ENABLE_PAIRING_BONDING = 0`). Without pairing, the
  Wi-Fi password would travel over the air in the clear.
- **The Pico's own network: chosen.** It works with the official MicroPython and with the Wi-Fi the Pico already uses.

## How it works

1. **With no saved network**, the Pico immediately opens the setup network **`AmpLink-SP103-XXXX`** (XXXX = the end of the
   chip's address). The password is **`amplink-setup`**, the same on every Pico; the app knows it. Every setup network starts
   with `AmpLink-` (the MR 780 will open `AmpLink-MR780-XXXX`): the app asks Android for a network with that prefix, without
   needing the location permission to scan for networks.
2. **With a saved network that does not connect** (router password changed, router off), the Pico keeps trying every
   30 s and, after 2 minutes without success, also opens the setup network.
3. Whoever joins the setup network (the app, or the phone's browser at `http://192.168.4.1/`) picks the network and
   sends the password. The Pico connects **without closing the setup network**, so whoever set it up can read the IP, and closes it 60 s
   later. If the new network fails, it goes back to the previous one and says why.
4. **Changing network with the Pico connected:** `POST /wifi/setup` opens the setup network for 10 minutes, without leaving the
   home network.
5. **Finding the Pico:** the app sends `DEVICELINK?` by UDP broadcast, port **47800**, and the Pico answers
   `{"name": "SP103-D85E", "model": "sp103", "ip": "192.168.1.77", "api": 2, "label": "Acoustic Solutions SP103",
   "kind": "amplifier"}`. Send it about 3 times in 2 s: the first packet is
   sometimes lost.

The setup network is only open when the Pico has no Wi-Fi (or for 10 minutes, when requested). A fixed password
is enough for that: whoever joins it can only change the Pico's network.

## Routes

| Route | What |
|---|---|
| `GET /wifi` | `{"state", "detail", "ip", "ssid", "setup": {"open", "ssid"}}`. `state` and `detail` are the last attempt: `idle`, `connecting`, `connected`, or `failed` with the reason (`wrong password`, `network not found`, `connection failed`, `timeout`). `ip` is the current address on the home network; `ssid`, the saved network |
| `GET /wifi/networks` | The networks the Pico sees: `[{"ssid", "rssi", "secure"}]`, one per name, strongest to weakest, up to 20. Takes ~1 s |
| `PUT /wifi` | `{"ssid": "Casa", "psk": "..."}` (no `psk`, or empty = open network; otherwise 8 to 63 characters). Answers `202` right away; the result shows in `GET /wifi`. **Only with the setup network open**, otherwise `403` |
| `POST /wifi/setup` | Opens the setup network for 10 minutes |
| `DELETE /wifi` | Forgets the saved network. Only with the setup network open |
| `GET /` | The setup page (pick the network and type the password), only with the setup network open. Otherwise, the Pico still has no web page |

The routes also answer on the home network: the app can read `GET /wifi` at any time.

## Picos installed before this version

Without `wifi.json`, the Pico uses `WIFI_SSID` and `WIFI_PASSWORD` from `secrets.py`, as before. On the first setup
through its own network, `wifi.json` takes over, and those two lines in `secrets.py` can go (over the cable, when
convenient). `UPDATE_PASSWORD` stays in `secrets.py`.

`wifi.json` is not a `.py`: the update over Wi-Fi (`wifi-update.md`) never sends, deletes or restores it.

## Pico details found on the bench

- In MicroPython's `WLAN.scan()` for the Pico, the 6th field is a count (always 1 or more), not "hidden network". A hidden
  network only shows up with an empty name.
- Scanning works with the setup network open.
- A request body must be read before the response: if the Pico closes the connection with unread bytes, the client
  loses the response.
- Networks with a login page or with a username (hotel, company) do not work: the Pico has no way to fill them in.
