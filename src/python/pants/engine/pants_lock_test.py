# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from pants.engine.pants_lock import pants_lock_bin


def _open_lock_fd(lock_path: Path) -> int:
    return os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o644)


def _lock(fd: int) -> subprocess.Popen[str]:
    """Run pants_lock on the given fd, which is inherited by the subprocess."""
    return subprocess.Popen(
        [pants_lock_bin(), str(fd)], pass_fds=(fd,), stderr=subprocess.PIPE, text=True
    )


def test_acquire_and_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "test.lock"
    fd = _open_lock_fd(lock_path)
    try:
        # pants_lock exits 0 once the lock is acquired. The lock is then held by the
        # open file description underlying fd, i.e., by this process.
        assert _lock(fd).wait(timeout=30) == 0
    finally:
        os.close(fd)


def test_lock_is_exclusive_and_blocks(tmp_path: Path) -> None:
    lock_path = tmp_path / "test.lock"
    fd_a = _open_lock_fd(lock_path)
    fd_b = _open_lock_fd(lock_path)
    proc_b: subprocess.Popen[str] | None = None
    try:
        assert _lock(fd_a).wait(timeout=30) == 0

        # A second locker, via a distinct open file description on the same file,
        # must block while the first lock is held.
        proc_b = _lock(fd_b)
        time.sleep(2)
        assert proc_b.poll() is None, "second locker did not block while the lock was held"

        # Closing the fd that holds the lock releases it, unblocking the second locker.
        os.close(fd_a)
        assert proc_b.wait(timeout=30) == 0
    finally:
        if proc_b is not None and proc_b.poll() is None:
            proc_b.kill()
            proc_b.wait()
        os.close(fd_b)


def test_relock_after_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "test.lock"
    for _ in range(2):
        fd = _open_lock_fd(lock_path)
        try:
            assert _lock(fd).wait(timeout=30) == 0
        finally:
            os.close(fd)


def test_fails_on_bad_fd() -> None:
    # An fd that is not open in the subprocess.
    result = subprocess.run([pants_lock_bin(), "173"], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Failed to lock fd 173" in result.stderr


def test_usage_errors() -> None:
    for argv in ([], ["not-a-number"], ["200", "extra"]):
        result = subprocess.run([pants_lock_bin(), *argv], capture_output=True, text=True)
        assert result.returncode != 0
        assert "Usage" in result.stderr
