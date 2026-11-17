# Updating the Pico's program over Wi-Fi

With the Pico installed inside the amp, the USB cable is hard to use (and with the VSYS wire connected, it is even dangerous: see
`installation.md`, "USB rule"). So the new program goes over Wi-Fi, and the Pico **goes back on its own to the previous
version** if the new one does not work. It can be sent from the computer (`tools/enviar.py`) or from the DeviceLink app,
which installs the latest GitHub release of this repository.

**No password since 2026-11-17** (version 973fed99): `ota.py`, `enviar.py` and the other shared files now come from the
bridges' shared base (device-link `firmware-base/`, copied with `copiar.py --skip firmware/main.py`), as decided for
contract v2. Before that, every request carried an `X-Password` header; the history below mentions it.

Programs: `firmware/ota.py` (on the Pico, receives), `firmware/main.py` (on the Pico, decides whether to roll back) and `tools/enviar.py` (on the
computer, sends).

## Preparing (once only, over the cable)

1. With the Pico on USB (and the VSYS wire disconnected, if it is in the amp), send the files:

   ```sh
   cd firmware
   ../.venv/bin/mpremote cp *.py :
   ../.venv/bin/mpremote reset
   ```

Done on 2026-10-24: the amp's Pico is already set up like this.

## Sending a new version

```sh
python3 tools/enviar.py
```

It does everything on its own:

1. Asks the Pico (`http://sp103.local/update`) which files it has.
2. Checks the syntax of the `firmware/` files on the computer and sends only the ones that changed.
3. Marks for deletion the `.py` files that are on the Pico but no longer exist in `firmware/` (only when it sends the whole folder).
4. The Pico saves **the whole current version** in the `old/` folder, swaps and deletes the files.
5. The Pico restarts and the new version is **on trial**. It is confirmed when, for 20 s in a row, the program runs, the
   Wi-Fi is connected and someone (`enviar.py` itself) can talk to the Pico.
6. `enviar.py` shows "Done: version ... confirmed", in about 30 s.

If the new version **fails**, the Pico goes back to the previous one on its own:

| What happens with the new version | When the Pico rolls back |
|---|---|
| Errors on start | about 40 s (shows the error for 30 s and restarts) |
| Hangs, does not connect to Wi-Fi or does not respond | 3 min (the `main.py` timer runs out and it restarts) |
| Power cut during the trial | on the next boot (to be safe, it counts as a failure) |

`enviar.py` warns: "The new version FAILED and the Pico went back to the previous one". To see the error, connect the Pico by cable and
run the new version with `mpremote` (with the amp unplugged from the wall and the red wire disconnected):

```sh
cd firmware
../.venv/bin/mpremote mount . run proxy.py
```

`mount` makes the Pico use the computer's files. If `mpremote` is interrupted midway, the Pico keeps waiting for the
computer and does not go back to Wi-Fi: unplug and replug the USB.

## Other commands

```sh
python3 tools/enviar.py --status           # current version, state and saved version
python3 tools/enviar.py --rollback         # go back to the saved version (the one before the last update)
python3 tools/enviar.py proxy.py           # send only this file (if it changed; deletes nothing)
python3 tools/enviar.py --host 192.168.178.108    # if sp103.local does not work
python3 tools/enviar.py --publish          # make the GitHub release the app updates from (needs gh)
```

The old Portuguese flags (`--estado`, `--voltar`, `--forcar`) still work.

The "version" is an 8-letter code that changes whenever any file changes.

## What never goes over Wi-Fi

- **`main.py`**: it is the "gatekeeper" that does the rollback. If it broke, nothing would roll back any more. Changed `main.py`? Cable only.
- **`secrets.py`**: optional now (it held the update password until 2026-11-17). Cable only. (The Wi-Fi network lives in
  `wifi.json`, changed through the Pico's setup network, `wifi.md`.)
- **`wifi.json`**: the saved Wi-Fi network. The update never touches it.
- **`names.json`**: the custom texts stay on the Pico and are edited on its own page (`firmware/config_page.py`).

## Security

- No password: the routes answer on the home network only, like the rest of the bridge, and a bad version rolls itself back
  (contract v2, "Updates from the app"). `main.py` and `secrets.py` are refused over Wi-Fi.
- Until 2026-11-17 the password went in the `X-Password` header, and a wrong one took 1 s to be refused.

## Tested

On the bench (2026-10-24):

- Three real updates (`web.py`, `buslog.py`, `ota.py`): confirmed in ~30 s.
- Version that errors on start: rolled back on its own in 38 s.
- Version that hangs: rolled back on its own in 189 s.
- `--voltar` (now `--rollback`) and resend: ok. Wrong password, file with a syntax error and `main.py`: refused, with a message.

On the amp (2026-10-29): the first proxy version errored on start and rolled back on its own; the fix was confirmed.
Deletion was used to remove the files of the unclipped writing from the Pico. The old `ota.py` could not delete, so it took
two sends: `enviar.py` warns when that happens.
