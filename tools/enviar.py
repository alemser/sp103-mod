#!/usr/bin/env python3
"""Sends the new program to the Pico over Wi-Fi (firmware/ota.py) and follows it until it confirms.

    python3 tools/enviar.py                    # sends what changed in firmware/, deletes from the Pico the .py
                                               # files that no longer exist, and applies
    python3 tools/enviar.py escuta.py web.py   # only these files (if they changed)
    python3 tools/enviar.py --status           # only shows the Pico's version and state
    python3 tools/enviar.py --rollback         # goes back to the previous version (kept on the Pico)

Options: --host (default sp103.local, or the SP103_HOST variable) and --force (send even unchanged files).
The old Portuguese flags (--estado, --voltar, --forcar) still work.
The password comes from UPDATE_PASSWORD in firmware/secrets.py (or the SP103_PASSWORD variable).

Never sends main.py or secrets.py: those go by USB only, with mpremote.
"""

import argparse
import glob
import hashlib
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FIRMWARE = os.path.join(HERE, "..", "firmware")
LOCKED = ("main.py", "secrets.py")
TRIAL_S = 180                   # the same as main.py
WAIT_S = TRIAL_S + 90           # restart + Wi-Fi + trial


def password():
    if os.environ.get("SP103_PASSWORD"):
        return os.environ["SP103_PASSWORD"]
    values = {}
    try:
        with open(os.path.join(FIRMWARE, "secrets.py")) as f:
            exec(f.read(), values)
    except OSError:
        pass
    if not values.get("UPDATE_PASSWORD"):
        sys.exit("Missing password: put UPDATE_PASSWORD = \"...\" in firmware/secrets.py "
                 "(and the same secrets.py on the Pico, by USB).")
    return values["UPDATE_PASSWORD"]


def request(host, method, path, body=None, pw=None, timeout=10):
    req = urllib.request.Request("http://%s%s" % (host, path), data=body, method=method)
    if pw:
        req.add_header("X-Password", pw)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error", e.reason)
        except (ValueError, OSError):   # the Pico answered before reading everything and closed the connection
            msg = e.reason
        sys.exit("The Pico refused (%d): %s" % (e.code, msg))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def version(files):
    """The same version code as ota.version()."""
    h = hashlib.sha256()
    for name in sorted(files):
        if name in LOCKED:
            continue
        h.update((name + files[name]).encode())
    return h.hexdigest()[:8]


def show(st):
    print("Version on the Pico: %s   state: %s%s" % (
        st["version"], st["state"], "  (%s)" % st["why"] if st.get("why") else ""))
    print("Previous version kept: %s" % (st["previous"] or "none"))
    if not st["enabled"]:
        print("Updating over Wi-Fi is OFF: UPDATE_PASSWORD is missing from the Pico's secrets.py.")


def local_files(names):
    paths = [os.path.join(FIRMWARE, n) for n in names] if names else \
        sorted(glob.glob(os.path.join(FIRMWARE, "*.py")))
    out = {}
    for path in paths:
        name = os.path.basename(path)
        if not name[:-3].replace("_", "").isalnum():
            continue                        # secrets.example.py and the like: not part of the program
        if name in LOCKED:
            if names:
                print("%s left out: USB only (.venv/bin/mpremote cp firmware/%s :%s)" % (
                    name, name, name))
            continue
        with open(path, "rb") as f:
            data = f.read()
        try:
            compile(data, name, "exec")     # a typo: better found here
        except SyntaxError as e:
            sys.exit("Syntax error in %s, line %s: %s" % (name, e.lineno, e.msg))
        out[name] = data
    return out


def rollback_trial(host, timeout=60):
    """Asks for the rollback once the trial started, even when the POST's answer was lost."""
    try:
        request(host, "POST", "/update/rollback", b"", password())
    except (http.client.RemoteDisconnected, ConnectionError, OSError, urllib.error.URLError):
        pass                            # confirmed by the state below; the answer may have been lost
    started = time.time()
    while time.time() - started < timeout:
        time.sleep(2)
        try:
            st = request(host, "GET", "/update", timeout=5)
        except (OSError, urllib.error.URLError):
            continue
        if st["state"] == "rolled_back":
            return st
    return None


def wait(host, expected, expected_files, started):
    """Follows the restart and the new version's trial, until it confirms or goes back."""
    last = None
    while time.time() - started < WAIT_S:
        time.sleep(2)
        try:
            st = request(host, "GET", "/update", timeout=5)
        except (OSError, urllib.error.URLError):
            msg = "Pico restarting (no answer yet)..."
        else:
            if st["state"] == "ok" and st["version"] == expected:
                mismatched = sorted(n for n, digest in expected_files.items()
                                    if st["files"].get(n) != digest)
                if mismatched:
                    print("\nThe version has the expected code, but the hashes don't match: %s." %
                          ", ".join(mismatched))
                    return False
                print("\nDone: version %s confirmed. The previous one (%s) is kept on the Pico." % (
                    expected, st["previous"]))
                return True
            if st["state"] == "rolled_back":
                print("\nThe new version FAILED and the Pico went back to the previous one (%s): %s." % (
                    st["version"], st["why"]))
                print("See the error over USB: .venv/bin/mpremote (the Pico shows it at boot).")
                return False
            if st["state"] == "trial":
                mismatched = sorted(n for n, digest in expected_files.items()
                                    if st["files"].get(n) != digest)
                if mismatched:
                    print("\nRemote hash differs during the trial: %s. Asking for a rollback..." %
                          ", ".join(mismatched))
                    old = rollback_trial(host)
                    if old:
                        print("The Pico went back safely to version %s." % old["version"])
                    else:
                        print("Couldn't confirm the rollback; check with --status before deploying again.")
                    return False
                msg = "Version %s on trial; hashes match (the Pico confirms after 20 s running)..." % st["version"]
            else:
                msg = "State: %s, version %s" % (st["state"], st["version"])
        if msg != last:
            print("  %3d s  %s" % (time.time() - started, msg))
            last = msg
    print("\nThe Pico didn't confirm within %d s. It goes back to the previous version by itself;" % WAIT_S)
    print("check with: python3 tools/enviar.py --status")
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", help="files from firmware/ (default: every .py)")
    ap.add_argument("--host", default=os.environ.get("SP103_HOST", "sp103.local"))
    ap.add_argument("--status", "--estado", dest="status", action="store_true", help="only show the state")
    ap.add_argument("--rollback", "--voltar", dest="rollback", action="store_true",
                    help="go back to the previous version")
    ap.add_argument("--force", "--forcar", dest="force", action="store_true", help="send even unchanged files")
    args = ap.parse_args()
    host = args.host

    try:
        st = request(host, "GET", "/update")
    except (OSError, urllib.error.URLError) as e:
        sys.exit("Couldn't find the Pico at %s (%s). Is it on and on the Wi-Fi? "
                 "Try --host with its IP." % (host, getattr(e, "reason", e)))
    show(st)
    if args.status:
        return

    pw = password()
    if args.rollback:
        if not st["previous"]:
            sys.exit("No previous version kept on the Pico.")
        if st["previous"] == st["version"]:
            sys.exit("The Pico already runs the kept version (%s): nothing to go back to." % st["version"])
        request(host, "POST", "/update/rollback", b"", pw)
        print("Going back to version %s..." % st["previous"])
        started = time.time()
        while time.time() - started < 60:
            time.sleep(2)
            try:
                st = request(host, "GET", "/update", timeout=5)
            except (OSError, urllib.error.URLError):
                continue
            if st["state"] == "rolled_back":
                print("Done: the Pico runs version %s." % st["version"])
                return
        sys.exit("The Pico didn't answer within 60 s.")

    if st["state"] == "trial":
        sys.exit("The last update is still on trial. Wait a few minutes and try again.")

    files = local_files(args.files)
    if not args.files:
        with open(os.path.join(FIRMWARE, "main.py"), "rb") as f:
            if sha(f.read()) != st["files"].get("main.py"):
                print("Note: the Pico's main.py differs from firmware/main.py. It doesn't go over Wi-Fi;\n"
                      "      if needed, by USB: .venv/bin/mpremote cp firmware/main.py :main.py")
    send = {n: d for n, d in files.items() if args.force or sha(d) != st["files"].get(n)}
    # Only with the whole firmware/ can we tell what is left over on the Pico.
    remove = [] if args.files else sorted(n for n in st["files"] if n not in LOCKED and n not in files)
    if remove and not st.get("can_delete"):
        print("Left over on the Pico: %s, but its ota.py can't delete yet.\n"
              "Send this version and run again to delete them." % ", ".join(remove))
        remove = []
    if not send and not remove:
        print("Nothing changed: the Pico already has these files.")
        return

    if send:
        print("\nSending %d file(s):" % len(send))
    request(host, "POST", "/update/cancel", b"", pw)
    for name, data in send.items():
        try:
            got = request(host, "PUT", "/update/" + name, data, pw, timeout=30)
        except (http.client.RemoteDisconnected, ConnectionError, OSError, urllib.error.URLError) as e:
            # Some MicroPython builds close the connection after writing the body, before the JSON answer reaches
            # the computer. The staged name only proves it reached the temporary file; integrity is checked by the
            # active SHA-256s during the trial, before the update may confirm.
            check = request(host, "GET", "/update", timeout=5)
            if name not in check["staged"]:
                sys.exit("Answer lost while sending %s, and the file is not staged (%s). "
                         "Nothing was applied." % (name, e))
            print("  %-20s HTTP answer lost; staged, hash checked during the trial" % name)
        else:
            if got["sha256"] != sha(data):
                sys.exit("%s arrived different; nothing was applied. Try again." % name)
            print("  %-20s %6d bytes  ok" % (name, len(data)))
    if remove:
        print("\nDeleting from the Pico %d file(s) no longer in firmware/:" % len(remove))
        for name in remove:
            request(host, "DELETE", "/update/" + name, None, pw)
            print("  %-20s marked" % name)

    expected_files = dict(st["files"])
    expected_files.update({n: sha(d) for n, d in send.items()})
    for name in remove:
        del expected_files[name]
    expected = version(expected_files)
    try:
        request(host, "POST", "/update/apply", b"", pw)
    except (http.client.RemoteDisconnected, ConnectionError, OSError, urllib.error.URLError):
        # The answer may vanish if the Pico starts its reset right after accepting the apply.
        pass
    print("\nApplied. New version: %s. The Pico restarts and tries the new version:" % expected)
    sys.exit(0 if wait(host, expected, expected_files, time.time()) else 1)


if __name__ == "__main__":
    main()
