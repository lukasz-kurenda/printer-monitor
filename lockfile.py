# -*- coding: utf-8 -*-
"""Run lock mechanism (OPS-W5): PID + timestamp + stale-lock detection.

Lock file (JSON): {"pid": ..., "ts": ..., "cmd": ...}
A lock is considered active when: the pid is alive AND the file is younger than max_age_seconds.
A dead PID or an old file = stale-lock -> can be taken over.
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
    """True if a live process holds the lock (and it is not stale)."""
    data = _lock_data(lock_path)
    if not data:
        return False
    if time.time() - data.get("ts", 0) > max_age_seconds:
        return False
    return _pid_alive(data.get("pid"))


def acquire(lock_path, max_age_seconds=3600):
    """Try to take over the lock. Returns True (acquired) or False (another active)."""
    if is_locked(lock_path, max_age_seconds):
        return False
    data = {"pid": os.getpid(), "ts": time.time(), "cmd": "printer-monitor"}
    tmp = lock_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, lock_path)
    return True


def release(lock_path):
    """Remove the lock only if it belongs to the current process."""
    data = _lock_data(lock_path)
    if data and data.get("pid") == os.getpid():
        try:
            os.remove(lock_path)
        except OSError:
            pass
