# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest.mock
from contextlib import contextmanager

import psutil

from pants.java.nailgun_executor import NailgunExecutor
from pants.testutil.test_base import TestBase

PATCH_OPTS = dict(autospec=True, spec_set=True)


def fake_process(**kwargs):
    proc = unittest.mock.create_autospec(psutil.Process, spec_set=True)
    [setattr(getattr(proc, k), "return_value", v) for k, v in kwargs.items()]
    return proc


@contextmanager
def rw_pipes(write_input=None):
    """Create a pair of pipes wrapped in python file objects.

    :param str write_input: If `write_input` is not None, the writable pipe will have that string
                            written to it, then closed.
    """
    read_pipe, write_pipe = os.pipe()
    read_fileobj = os.fdopen(read_pipe, "r")
    write_fileobj = os.fdopen(write_pipe, "w")

    if write_input is not None:
        write_fileobj.write(write_input)
        write_fileobj.close()
        write_fileobj = None

    yield read_fileobj, write_fileobj

    read_fileobj.close()

    if write_fileobj is not None:
        write_fileobj.close()


class NailgunExecutorTest(TestBase):
    def setUp(self):
        super().setUp()
        self.executor = NailgunExecutor(
            identity="test",
            workdir="/__non_existent_dir",
            nailgun_classpath=[],
            distribution=unittest.mock.Mock(),
            metadata_base_dir=self.subprocess_dir,
        )

    def test_is_alive_override(self):
        with unittest.mock.patch.object(
            NailgunExecutor, "_as_process", **PATCH_OPTS
        ) as mock_as_process:
            mock_as_process.return_value = fake_process(
                name="java",
                pid=3,
                status=psutil.STATUS_IDLE,
                cmdline=[b"java", b"-arg", NailgunExecutor._PANTS_NG_BUILDROOT_ARG],
            )
            self.assertTrue(self.executor.is_alive())
            mock_as_process.assert_called_with(self.executor)

    def test_is_alive_override_not_my_process(self):
        with unittest.mock.patch.object(
            NailgunExecutor, "_as_process", **PATCH_OPTS
        ) as mock_as_process:
            mock_as_process.return_value = fake_process(
                name="java", pid=3, status=psutil.STATUS_IDLE, cmdline=[b"java", b"-arg", b"-arg2"]
            )
            self.assertFalse(self.executor.is_alive())
            mock_as_process.assert_called_with(self.executor)

    def test_connect_timeout(self):
        with rw_pipes() as (stdout_read, _), unittest.mock.patch(
            "pants.java.nailgun_executor.safe_open"
        ) as mock_open, unittest.mock.patch(
            "pants.java.nailgun_executor.read_file"
        ) as mock_read_file:
            mock_open.return_value = stdout_read
            mock_read_file.return_value = "err"
            # The stdout write pipe has no input and hasn't been closed, so the selector.select() should
            # time out regardless of the timeout argument, and raise.
            with self.assertRaisesWithMessage(
                NailgunExecutor.InitialNailgunConnectTimedOut,
                """\
Failed to read nailgun output after 0.0001 seconds!
Stdout:

Stderr:
err""",
            ):
                self.executor._await_socket(timeout=0.0001)
