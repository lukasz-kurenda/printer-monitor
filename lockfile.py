# -*- coding: utf-8 -*-
"""Mechanizm blokady uruchomien (OPS-W5): PID + znacznik czasu + stale-lock.

Plik blokady (JSON): {"pid": ..., "ts": ..., "cmd": ...}
Blokada uznawana za aktywna gdy: pid zyje ORAZ plik mlodszy niz max_age_seconds.
Martwy PID albo stary plik = stale-lock -> mozna przejac.
"""

import json
import os
import time


def _lock_data(lock_path):
    try:
        with open(lock_path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_locked(lock_path, max_age_seconds=3600):
    """True, jesli blokade trzyma zywy proces (i nie jest stara)."""
    data = _lock_data(lock_path)
    if not data:
        return False
    if time.time() - data.get("ts", 0) > max_age_seconds:
        return False
    return _pid_alive(data.get("pid"))


def acquire(lock_path, max_age_seconds=3600):
    """Probuje przejac blokade. Zwraca True (przejeto) lub False (aktywny inny)."""
    if is_locked(lock_path, max_age_seconds):
        return False
    data = {"pid": os.getpid(), "ts": time.time(), "cmd": "printer-monitor"}
    tmp = lock_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, lock_path)
    return True


def release(lock_path):
    """Usuwa blokade tylko jesli nalezy do biezacego procesu."""
    data = _lock_data(lock_path)
    if data and data.get("pid") == os.getpid():
        try:
            os.remove(lock_path)
        except OSError:
            pass
