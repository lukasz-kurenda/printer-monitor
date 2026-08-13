# -*- coding: utf-8 -*-
"""Lock mechanism tests (OPS-W5)."""

import json
import os
import time

import lockfile


def _write_lock(path, pid, ts):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"pid": pid, "ts": ts, "cmd": "test"}, fh)


def test_is_locked_alive_pid(tmp_path):
    path = str(tmp_path / "script.lock")
    _write_lock(path, os.getpid(), time.time())
    assert lockfile.is_locked(path) is True


def test_is_locked_dead_pid(tmp_path):
    path = str(tmp_path / "script.lock")
    _write_lock(path, 999999, time.time())
    assert lockfile.is_locked(path) is False


def test_is_locked_old_file(tmp_path):
    path = str(tmp_path / "script.lock")
    _write_lock(path, os.getpid(), time.time() - 7200)
    assert lockfile.is_locked(path, max_age_seconds=3600) is False


def test_is_locked_missing_file(tmp_path):
    assert lockfile.is_locked(str(tmp_path / "nope.lock")) is False


def test_is_locked_corrupt_file(tmp_path):
    path = tmp_path / "script.lock"
    path.write_text("not json")
    assert lockfile.is_locked(str(path)) is False


def test_acquire_and_release(tmp_path):
    path = str(tmp_path / "script.lock")
    assert lockfile.acquire(path) is True
    assert lockfile.is_locked(path) is True
    assert lockfile.acquire(path) is False  # live owner -> denied
    lockfile.release(path)
    assert lockfile.is_locked(path) is False


def test_acquire_takes_over_stale(tmp_path):
    path = str(tmp_path / "script.lock")
    _write_lock(path, 999999, time.time())
    assert lockfile.acquire(path) is True


def test_release_only_own_pid(tmp_path):
    path = str(tmp_path / "script.lock")
    _write_lock(path, 999999, time.time())
    lockfile.release(path)
    assert os.path.exists(path) is True
