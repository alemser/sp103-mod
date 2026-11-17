# Updating the Pico's program over Wi-Fi

With the Pico installed inside the amp, the USB cable is hard to use (and with the VSYS wire connected, it is even dangerous: see
`proxy-ligacao.md`, "USB rule"). So the new program goes over Wi-Fi, with a password, and the Pico **goes back on its own to the
previous version** if the new one does not work.

The newer bridges' shared base now takes updates over Wi-Fi without a password. This SP103 firmware still has its own
`firmware/ota.py`, which requires the password described here.

Programs: `firmware/ota.py` (on the Pico, receives), `firmware/main.py` (on the Pico, decides whether to roll back) and `tools/enviar.py` (on the
computer, sends).

## Preparing (once only, over the cable)

1. In `firmware/secrets.py` on the computer, the password line (it is already there, with a random password):

   ```python
   UPDATE_PASSWORD = "..."   # any text; enviar.py reads it from here
   ```

2. With the Pico on USB (and the VSYS wire disconnected, if it is in the amp), send the files:

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
```

The old Portuguese flags (`--estado`, `--voltar`, `--forcar`) still work.

The "version" is an 8-letter code that changes whenever any file changes.

## What never goes over Wi-Fi

- **`main.py`**: it is the "gatekeeper" that does the rollback. If it broke, nothing would roll back any more. Changed `main.py`? Cable only.
- **`secrets.py`**: holds the update password. To change it, cable only. (The Wi-Fi network no longer lives here: it lives in
  `wifi.json`, changed through the Pico's setup network, `wifi.md`.)
- **`wifi.json`**: the saved Wi-Fi network. The update never touches it.
- **`names.json`**: the custom texts stay on the Pico and are edited by the app.

## Security

- The password goes in the `X-Password` header, unencrypted (plain HTTP). On the home network that is enough. Use a password that
  is not used for anything else.
- A wrong password takes 1 s to be refused (to slow down anyone guessing).
- Without the `UPDATE_PASSWORD` line in the Pico's `secrets.py`, updates are off.

## Tested

On the bench (2026-10-24):

- Three real updates (`web.py`, `buslog.py`, `ota.py`): confirmed in ~30 s.
- Version that errors on start: rolled back on its own in 38 s.
- Version that hangs: rolled back on its own in 189 s.
- `--voltar` (now `--rollback`) and resend: ok. Wrong password, file with a syntax error and `main.py`: refused, with a message.

On the amp (2026-10-29): the first proxy version errored on start and rolled back on its own; the fix was confirmed.
Deletion was used to remove the files of the unclipped writing from the Pico. The old `ota.py` could not delete, so it took
two sends: `enviar.py` warns when that happens.
