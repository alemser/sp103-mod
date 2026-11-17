"""Firmware update over Wi-Fi, with automatic rollback.

This file belongs to the shared base (device-link, firmware-base/): change it there and copy it with copiar.py, never here.

Used by tools/enviar.py on the computer and by the DeviceLink app (docs/contract-v2.md). No password: the routes are on
the home LAN only, and a bad version rolls itself back.

    GET    /update            state: version, files (sha256), staged files
    PUT    /update/<name>.py  receives a file into new/ (checks its syntax)
    DELETE /update/<name>.py  marks a file for deletion at the next apply
    POST   /update/cancel     drops what was received and not applied
    POST   /update/apply      keeps the running version in old/, applies new/, restarts
    POST   /update/rollback   goes back to the version in old/ and restarts

Deleting also goes through old/: if the new version fails, main.py brings the file back.

After apply the new version is on trial (update.json, state "trial"). The bridge program calls confirm() once it proves
healthy; if it doesn't, main.py restores the previous version (see main.py, which only changes over USB).
"""

import os
import json
import hashlib
import asyncio
import machine
from binascii import hexlify

from web import reply_json

MARKER = "update.json"          # the same names as main.py
OLD = "old"
NEW = "new"
LOCKED = ("main.py", "secrets.py")   # USB only: the gatekeeper and the secrets
DELETE = ".del"                 # new/<name>.py.del = delete <name>.py at apply


def _marker():
    try:
        with open(MARKER) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(m):
    with open(MARKER, "w") as f:
        json.dump(m, f)


def in_trial():
    return _marker().get("state") == "trial"


def confirm():
    """The new version works: it stays (old/ keeps the previous one)."""
    m = _marker()
    if m.get("state") == "trial":
        m["state"] = "ok"
        _save(m)
        print("update: new version confirmed")


def _ls(folder=""):
    try:
        return sorted(os.listdir(folder))
    except OSError:
        return []


def _path(folder, name):
    return folder + "/" + name if folder else name


def _sha(path):
    h = hashlib.sha256()
    buf = bytearray(1024)
    with open(path, "rb") as f:
        while True:
            n = f.readinto(buf)
            if not n:
                break
            h.update(buf[:n])
    return hexlify(h.digest()).decode()


def _copy(src, dst):
    buf = bytearray(1024)
    with open(src, "rb") as a, open(dst, "wb") as b:
        while True:
            n = a.readinto(buf)
            if not n:
                break
            b.write(buf[:n])


def _clear(folder):
    for name in _ls(folder):
        os.remove(_path(folder, name))
    if folder not in os.listdir():
        os.mkdir(folder)


def _program(folder=""):
    """The program's files in a folder (secrets.py is left out: it holds secrets)."""
    return [n for n in _ls(folder) if n.endswith(".py") and n != "secrets.py"]


def _files(folder=""):
    return {name: _sha(_path(folder, name)) for name in _program(folder)}


def version(files):
    """A short code that changes whenever a program file changes (except main.py, which doesn't go to old/, so the
    kept previous version has the same code it had before)."""
    h = hashlib.sha256()
    for name in sorted(files):
        if name in LOCKED:
            continue
        h.update((name + files[name]).encode())
    return hexlify(h.digest()).decode()[:8]


_current = None                 # the program only changes by restarting: computed once


async def current_version():
    """status()'s version, without stalling the bridge: reading every file in one go takes about 0.6 s."""
    global _current
    if _current is None:
        files = {}
        for name in _program():
            files[name] = _sha(name)
            await asyncio.sleep(0)
        _current = version(files)
    return _current


def status():
    m = _marker()
    files = _files()
    return {"version": version(files), "state": m.get("state", "ok"), "why": m.get("why"),
            "previous": version(_files(OLD)) if _ls(OLD) else None, "files": files,
            "staged": _ls(NEW), "enabled": True, "can_delete": True}


def _valid_name(name):
    base = name[:-3]
    return (name.endswith(".py") and 0 < len(base) <= 32 and name not in LOCKED
            and all(c.isalpha() or c.isdigit() or c == "_" for c in base))


async def _discard(req):
    """Reads and drops the request body: answering without reading it drops the connection and the client never
    sees the error message."""
    left = req.length
    while left > 0:
        chunk = await req.reader.read(min(1024, left))
        if not chunk:
            break
        left -= len(chunk)


async def _stage(req, name):
    """Receives a file into new/ and checks that MicroPython can read the code."""
    if not _valid_name(name):
        await _discard(req)
        raise ValueError("%s cannot be updated over Wi-Fi" % name)
    if NEW not in os.listdir():
        os.mkdir(NEW)
    path = _path(NEW, name)
    left = req.length
    with open(path, "wb") as f:
        while left > 0:
            chunk = await req.reader.read(min(1024, left))
            if not chunk:
                break
            f.write(chunk)
            left -= len(chunk)
    if left:
        os.remove(path)
        raise ValueError("%s arrived incomplete" % name)
    try:
        with open(path) as f:
            compile(f.read(), name, "exec")
    except SyntaxError as e:
        os.remove(path)
        raise ValueError("%s: syntax error: %s" % (name, e))
    return _sha(path)


def _stage_delete(name):
    """Marks a program file for deletion at the next apply."""
    if not _valid_name(name):
        raise ValueError("%s cannot be deleted over Wi-Fi" % name)
    if name not in _program():
        raise ValueError("%s is not on the Pico" % name)
    if NEW not in os.listdir():
        os.mkdir(NEW)
    open(_path(NEW, name + DELETE), "wb").close()


def _apply():
    staged = _ls(NEW)
    if not staged:
        raise ValueError("nothing to apply: send the files first")
    if in_trial():
        raise ValueError("the last update is still on trial; wait for it to confirm")
    # 1. The whole running version goes to old/ (main.py goes back to it if the new one fails).
    _clear(OLD)
    for name in _ls():
        if name.endswith(".py") and name != "main.py":
            _copy(name, _path(OLD, name))
    # 2. Mark "trial" BEFORE swapping: if the power goes midway, main.py goes back.
    _save({"state": "trial", "boots": 0, "files": staged})
    # 3. Swap (or delete) the files.
    for name in staged:
        target = name[:-len(DELETE)] if name.endswith(DELETE) else name
        if target in os.listdir():
            os.remove(target)
        if target == name:
            os.rename(_path(NEW, name), name)
        else:
            os.remove(_path(NEW, name))
    m = _marker()
    m["version"] = version(_files())
    _save(m)
    return m


async def _reset_soon():
    await asyncio.sleep(1)              # gives the answer time to reach the client
    machine.reset()


async def handle(req, writer):
    """Route /update (see web.Publisher)."""
    if req.method == "GET" and req.path == "/update":
        return await reply_json(writer, status())
    # No password (contract v2, decided 2026-11-16): home LAN only, and a bad version rolls itself back.
    action = req.path[len("/update/"):]
    try:
        if req.method == "PUT":
            answer = {"file": action, "sha256": await _stage(req, action)}
        elif req.method == "DELETE":
            _stage_delete(action)
            answer = {"file": action, "delete": True}
        elif req.method == "POST" and action == "cancel":
            _clear(NEW)
            answer = {"staged": []}
        elif req.method == "POST" and action == "apply":
            answer = _apply()
            print("update: applied %s, restarting" % answer["files"])
            asyncio.create_task(_reset_soon())
        elif req.method == "POST" and action == "rollback":
            if not _ls(OLD):
                raise ValueError("there is no previous version saved")
            _save({"state": "rollback"})
            print("update: rollback requested, restarting")
            asyncio.create_task(_reset_soon())
            answer = {"state": "rollback"}
        else:
            return await reply_json(writer, {"error": "unknown request"}, "404 Not Found")
    except (ValueError, OSError) as e:
        return await reply_json(writer, {"error": str(e)}, "400 Bad Request")
    await reply_json(writer, answer)
