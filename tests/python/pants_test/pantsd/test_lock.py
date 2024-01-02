# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
import tempfile
import unittest
from multiprocessing import Manager, Process
from threading import Thread

from pants.pantsd.lock import OwnerPrintingInterProcessFileLock


def hold_lock_until_terminate(path, lock_held, terminate):
    lock = OwnerPrintingInterProcessFileLock(path)
    lock.acquire()
    lock_held.set()
    # NOTE: We shouldn't ever wait this long, this is just to ensure
    # we don't somehow leak child processes.
    terminate.wait(60)
    lock.release()
    lock_held.clear()


class TestOwnerPrintingInterProcessFileLock(unittest.TestCase):
    def setUp(self):
        self.lock_dir = tempfile.mkdtemp()
        self.lock_path = os.path.join(self.lock_dir, "lock")
        self.lock = OwnerPrintingInterProcessFileLock(self.lock_path)
        self.manager = Manager()
        self.lock_held = self.manager.Event()
        self.terminate = self.manager.Event()
        self.lock_process = Process(
            target=hold_lock_until_terminate, args=(self.lock_path, self.lock_held, self.terminate)
        )

    def tearDown(self):
        self.terminate.set()
        try:
            shutil.rmtree(self.lock_dir)
        except OSError:
            pass

    def test_non_blocking_attempt(self):
        self.lock_process.start()
        self.lock_held.wait()
        self.assertFalse(self.lock.acquire(blocking=False))

    def test_message(self):
        self.lock_process.start()
        self.lock_held.wait()
        self.assertTrue(os.path.exists(self.lock.message_path))
        with open(self.lock.message_path) as f:
            message_content = f.read()
        self.assertIn(str(self.lock_process.pid), message_content)

        os.unlink(self.lock.message_path)

        def message_fn(message):
            self.assertIn(self.lock.missing_message_output, message)

        self.lock.acquire(blocking=False, message_fn=message_fn)

    def test_blocking(self):
        self.lock_process.start()
        self.lock_held.wait()
        self.assertFalse(self.lock.acquire(timeout=0.1))

        acquire_is_blocking = self.manager.Event()

        def terminate_subproc(terminate, acquire_is_blocking):
            acquire_is_blocking.wait()
            terminate.set()

        Thread(target=terminate_subproc, args=(self.terminate, acquire_is_blocking)).start()

        def message_fn(message):
            self.assertIn(str(self.lock_process.pid), message)
            acquire_is_blocking.set()

        # NOTE: We shouldn't ever wait this long (locally this runs in ~milliseconds)
        # but sometimes CI containers are extremely slow, so we choose a very large
        # value just in case.
        self.assertTrue(self.lock.acquire(timeout=30, message_fn=message_fn))

    def test_reentrant(self):
        self.assertTrue(self.lock.acquire())
        self.assertTrue(self.lock.acquire())

    def test_release(self):
        self.assertTrue(self.lock.acquire())
        self.assertTrue(self.lock.acquired)
        self.lock.release()
        self.assertFalse(self.lock.acquired)
