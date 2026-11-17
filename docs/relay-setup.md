# Installing the bridge on a board

The VU and the info screens depend on `sp103-vu-relay`, a program that runs on the board with the groove-detector. It
**is not in the Oceano image**, on purpose: only the SP103 uses it, and Oceano does not know the SP103 exists. The bridge is just one more
reader of what the detector publishes (the groove-detector's `docs/contracts.md`).

So do these steps whenever the capture moves to another board, or after flashing a new image to the card.

## Steps

Any Linux board with the groove-detector will do, 32 or 64 bits. In the repository folder, with the board's user and
IP:

1. Install:

   ```sh
   make -C relay deploy HOST=user@ip
   ```

2. In the app, the amp's "VU meter" settings, put the board's IP in **Source (the VU relay's IP)**. The Pico does not resolve `.local` names.

3. Check, with music playing:

   ```sh
   make -C relay check HOST=user@ip
   ```

   All good means both services `active`, frames arriving and `gate: music`.

## If it does not work

| What shows up | Likely cause |
|---|---|
| App: "No data from ... Is the VU relay running there?" | The bridge is not installed on that board, or the IP in the app belongs to another one |
| `make check`: no frames, with both services `active` | The board's firewall blocks UDP port 7091 (below) |
| `make check`: `gate: no music`, with music playing | The detector is not seeing the signal: check its capture |
| `make deploy`: "has no groove group" | The board does not have the groove-detector yet |

If the board uses `ufw`, open the port to the local network (replace with your network's range):

```sh
sudo ufw allow from 192.168.1.0/24 to any port 7091 proto udp comment sp103-vu-relay
```

When moving off a board, the bridge can stay there: without requests from the Pico, it sends nothing.
