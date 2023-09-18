# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import logging
import os
import subprocess
import sys
import time
import unittest
import unittest.mock
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent

import psutil
import pytest

from pants.pantsd.process_manager import ProcessManager
from pants.testutil.mock_time import MockTime
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_file_dump, safe_mkdtemp

PATCH_OPTS = dict(autospec=True, spec_set=True)


def fake_process(**kwargs):
    proc = unittest.mock.create_autospec(psutil.Process, spec_set=True)
    for k, v in kwargs.items():
        setattr(getattr(proc, k), "return_value", v)
    return proc


def test_deadline_until(monkeypatch, caplog):
    mock_time = MockTime()
    monkeypatch.setattr(time, "time", mock_time.time)
    monkeypatch.setattr(time, "sleep", mock_time.sleep)
    pm = ProcessManager("_test_", metadata_base_dir=safe_mkdtemp())
    with pytest.raises(ProcessManager.Timeout):
        with caplog.at_level(logging.INFO):
            pm._deadline_until(
                lambda: False, "the impossible", "completed? how?", timeout=0.5, info_interval=0.1
            )
    assert len(caplog.records) == 4, f"Expected 4 infos, got: {caplog.records}"


# TODO: Convert the rest of these tests to pytest-style test_* functions.
class TestProcessManager(unittest.TestCase):
    NAME = "_test_"
    TEST_KEY = "TEST"
    TEST_VALUE = "300"
    TEST_VALUE_INT = 300
    BUILDROOT = "/mock_buildroot/"

    def setUp(self):
        super().setUp()
        self.pm = ProcessManager(self.NAME, metadata_base_dir=safe_mkdtemp())
        self.pmm = self.pm

    def test_maybe_cast(self):
        self.assertIsNone(self.pmm._maybe_cast(None, int))
        self.assertEqual(self.pmm._maybe_cast("3333", int), 3333)
        self.assertEqual(self.pmm._maybe_cast("ssss", int), "ssss")

    def test_get_metadata_dir_by_name(self):
        pm = ProcessManager(self.NAME, metadata_base_dir=self.BUILDROOT)
        self.assertEqual(
            ProcessManager._get_metadata_dir_by_name(self.NAME, self.BUILDROOT),
            os.path.join(self.BUILDROOT, pm.host_fingerprint, self.NAME),
        )

    def test_readwrite_metadata_by_name(self):
        with temporary_dir() as tmpdir, unittest.mock.patch(
            "pants.pantsd.process_manager.get_buildroot", return_value=tmpdir
        ):
            self.pmm.write_metadata_by_name(self.TEST_KEY, self.TEST_VALUE)
            self.assertEqual(self.pmm.read_metadata_by_name(self.TEST_KEY), self.TEST_VALUE)
            self.assertEqual(
                self.pmm.read_metadata_by_name(self.TEST_KEY, int), self.TEST_VALUE_INT
            )

    def test_wait_for_file(self):
        with temporary_dir() as td:
            test_filename = os.path.join(td, "test.out")
            safe_file_dump(test_filename, "test")
            self.pmm._wait_for_file(
                test_filename, "file to be created", "file was created", timeout=0.1
            )

    def test_wait_for_file_timeout(self):
        with temporary_dir() as td:
            with self.assertRaises(ProcessManager.Timeout):
                self.pmm._wait_for_file(
                    os.path.join(td, "non_existent_file"),
                    "file to be created",
                    "file was created",
                    timeout=0.1,
                )

    def test_await_metadata_by_name(self):
        with temporary_dir() as tmpdir, unittest.mock.patch(
            "pants.pantsd.process_manager.get_buildroot", return_value=tmpdir
        ):
            self.pmm.write_metadata_by_name(self.TEST_KEY, self.TEST_VALUE)

            self.assertEqual(
                self.pmm.await_metadata_by_name(
                    self.TEST_KEY, "metadata to be created", "metadata was created", 0.1
                ),
                self.TEST_VALUE,
            )

    def test_purge_metadata(self):
        with unittest.mock.patch("pants.pantsd.process_manager.rm_rf") as mock_rm:
            self.pmm.purge_metadata_by_name(self.NAME)
        self.assertGreater(mock_rm.call_count, 0)

    def test_purge_metadata_error(self):
        with unittest.mock.patch("pants.pantsd.process_manager.rm_rf") as mock_rm:
            mock_rm.side_effect = OSError(errno.EACCES, os.strerror(errno.EACCES))
            with self.assertRaises(ProcessManager.MetadataError):
                self.pmm.purge_metadata_by_name(self.NAME)
        self.assertGreater(mock_rm.call_count, 0)

    def test_await_pid(self):
        with unittest.mock.patch.object(ProcessManager, "await_metadata_by_name") as mock_await:
            self.pm.await_pid(5)
        mock_await.assert_called_once_with(
            "pid", f"{self.NAME} to start", f"{self.NAME} started", 5, caster=unittest.mock.ANY
        )

    def test_await_socket(self):
        with unittest.mock.patch.object(ProcessManager, "await_metadata_by_name") as mock_await:
            self.pm.await_socket(5)
        mock_await.assert_called_once_with(
            "socket",
            f"{self.NAME} socket to be opened",
            f"{self.NAME} socket opened",
            5,
            caster=unittest.mock.ANY,
        )

    def test_write_pid(self):
        with unittest.mock.patch.object(ProcessManager, "write_metadata_by_name") as mock_write:
            self.pm.write_pid(31337)
        mock_write.assert_called_once_with("pid", "31337")

    def test_write_socket(self):
        with unittest.mock.patch.object(ProcessManager, "write_metadata_by_name") as mock_write:
            self.pm.write_socket("/path/to/unix/socket")
        mock_write.assert_called_once_with("socket", "/path/to/unix/socket")

    def test_as_process(self):
        sentinel = 3333
        with unittest.mock.patch("psutil.Process", **PATCH_OPTS) as mock_proc:
            mock_proc.return_value = sentinel
            self.pm.write_pid(sentinel)
            self.assertEqual(self.pm._as_process(), sentinel)

    def test_as_process_no_pid(self):
        fake_pid = 3
        with unittest.mock.patch("psutil.Process", **PATCH_OPTS) as mock_proc:
            mock_proc.side_effect = psutil.NoSuchProcess(fake_pid)
            self.pm.write_pid(fake_pid)
            with self.assertRaises(psutil.NoSuchProcess):
                self.pm._as_process()

    def test_as_process_none(self):
        with self.assertRaises(self.pm.NotStarted):
            self.pm._as_process()

    def test_is_alive_neg(self):
        with unittest.mock.patch.object(
            ProcessManager, "_as_process", **PATCH_OPTS
        ) as mock_as_process:
            mock_as_process.return_value = None
            self.assertFalse(self.pm.is_alive())
            mock_as_process.assert_called_once_with(self.pm)

    def test_is_alive(self):
        with unittest.mock.patch.object(
            ProcessManager, "_as_process", **PATCH_OPTS
        ) as mock_as_process:
            mock_as_process.return_value = fake_process(
                name="test", pid=3, status=psutil.STATUS_IDLE
            )
            self.assertTrue(self.pm.is_alive())
            mock_as_process.assert_called_with(self.pm)

    def test_is_alive_zombie(self):
        with unittest.mock.patch.object(
            ProcessManager, "_as_process", **PATCH_OPTS
        ) as mock_as_process:
            mock_as_process.return_value = fake_process(
                name="test", pid=3, status=psutil.STATUS_ZOMBIE
            )
            self.assertFalse(self.pm.is_alive())
            mock_as_process.assert_called_with(self.pm)

    def test_is_alive_zombie_exception(self):
        with unittest.mock.patch.object(
            ProcessManager, "_as_process", **PATCH_OPTS
        ) as mock_as_process:
            mock_as_process.side_effect = psutil.NoSuchProcess(0)
            self.assertFalse(self.pm.is_alive())
            mock_as_process.assert_called_with(self.pm)

    def test_is_alive_stale_pid(self):
        with unittest.mock.patch.object(
            ProcessManager, "_as_process", **PATCH_OPTS
        ) as mock_as_process:
            mock_as_process.return_value = fake_process(
                name="not_test", pid=3, status=psutil.STATUS_IDLE
            )
            self.pm.write_process_name("test")
            self.assertFalse(self.pm.is_alive())
            mock_as_process.assert_called_with(self.pm)

    def test_is_alive_extra_check(self):
        def extra_check(process):
            return False

        with unittest.mock.patch.object(
            ProcessManager, "_as_process", **PATCH_OPTS
        ) as mock_as_process:
            mock_as_process.return_value = fake_process(
                name="test", pid=3, status=psutil.STATUS_IDLE
            )
            self.assertFalse(self.pm.is_alive(extra_check))
            mock_as_process.assert_called_with(self.pm)

    def test_purge_metadata_aborts(self):
        with unittest.mock.patch.object(ProcessManager, "is_alive", return_value=True):
            with self.assertRaises(ProcessManager.MetadataError):
                self.pm.purge_metadata()

    def test_purge_metadata_alive_but_forced(self):
        with unittest.mock.patch.object(
            ProcessManager, "is_alive", return_value=True
        ), unittest.mock.patch("pants.pantsd.process_manager.rm_rf") as mock_rm_rf:
            self.pm.purge_metadata(force=True)
            self.assertGreater(mock_rm_rf.call_count, 0)

    def test_kill(self):
        with unittest.mock.patch("os.kill", **PATCH_OPTS) as mock_kill:
            self.pm.write_pid(42)
            self.pm._kill(0)
            mock_kill.assert_called_once_with(42, 0)

    def test_kill_no_pid(self):
        with unittest.mock.patch("os.kill", **PATCH_OPTS) as mock_kill:
            self.pm._kill(0)
            self.assertFalse(mock_kill.called, "If we have no pid, kills should noop gracefully.")

    @contextmanager
    def setup_terminate(self):
        with unittest.mock.patch.object(
            ProcessManager, "_kill", **PATCH_OPTS
        ) as mock_kill, unittest.mock.patch.object(
            ProcessManager, "is_alive", **PATCH_OPTS
        ) as mock_alive, unittest.mock.patch.object(
            ProcessManager, "purge_metadata", **PATCH_OPTS
        ) as mock_purge:
            yield mock_kill, mock_alive, mock_purge
            self.assertGreater(mock_alive.call_count, 0)

    def test_terminate_quick_death(self):
        with self.setup_terminate() as (mock_kill, mock_alive, mock_purge):
            mock_kill.side_effect = OSError("oops")
            mock_alive.side_effect = [True, False]
            self.pm.terminate(kill_wait=0.1)
            self.assertEqual(mock_kill.call_count, 1)
            self.assertEqual(mock_purge.call_count, 1)

    def test_terminate_quick_death_no_purge(self):
        with self.setup_terminate() as (mock_kill, mock_alive, mock_purge):
            mock_kill.side_effect = OSError("oops")
            mock_alive.side_effect = [True, False]
            self.pm.terminate(purge=False, kill_wait=0.1)
            self.assertEqual(mock_kill.call_count, 1)
            self.assertEqual(mock_purge.call_count, 0)

    def test_terminate_already_dead(self):
        with self.setup_terminate() as (mock_kill, mock_alive, mock_purge):
            mock_alive.return_value = False
            self.pm.terminate(purge=True)
            self.assertEqual(mock_kill.call_count, 0)
            self.assertEqual(mock_purge.call_count, 1)

    def test_terminate_no_kill(self):
        with self.setup_terminate() as (mock_kill, mock_alive, mock_purge):
            mock_alive.return_value = True
            with self.assertRaises(ProcessManager.NonResponsiveProcess):
                self.pm.terminate(kill_wait=0.1, purge=True)
            self.assertEqual(mock_kill.call_count, len(ProcessManager.KILL_CHAIN))
            self.assertEqual(mock_purge.call_count, 0)

    @contextmanager
    def mock_daemonize_context(self, chk_pre=True, chk_post_child=False, chk_post_parent=False):
        with unittest.mock.patch.object(
            ProcessManager, "post_fork_parent", **PATCH_OPTS
        ) as mock_post_parent, unittest.mock.patch.object(
            ProcessManager, "post_fork_child", **PATCH_OPTS
        ) as mock_post_child, unittest.mock.patch.object(
            ProcessManager, "pre_fork", **PATCH_OPTS
        ) as mock_pre, unittest.mock.patch.object(
            ProcessManager, "purge_metadata", **PATCH_OPTS
        ) as mock_purge, unittest.mock.patch(
            "os._exit", **PATCH_OPTS
        ), unittest.mock.patch(
            "os.chdir", **PATCH_OPTS
        ), unittest.mock.patch(
            "os.setsid", **PATCH_OPTS
        ), unittest.mock.patch(
            "os.waitpid", **PATCH_OPTS
        ), unittest.mock.patch(
            "os.fork", **PATCH_OPTS
        ) as mock_fork:
            yield mock_fork

            mock_purge.assert_called_once_with(self.pm)
            if chk_pre:
                mock_pre.assert_called_once_with(self.pm)
            if chk_post_child:
                mock_post_child.assert_called_once_with(self.pm)
            if chk_post_parent:
                mock_post_parent.assert_called_once_with(self.pm)

    def test_daemon_spawn_parent(self):
        with self.mock_daemonize_context(chk_post_parent=True) as mock_fork:
            mock_fork.return_value = 1  # Simulate the parent.
            self.pm.daemon_spawn()

    def test_daemon_spawn_child(self):
        with self.mock_daemonize_context(chk_post_child=True) as mock_fork:
            mock_fork.return_value = 0  # Simulate the child.
            self.pm.daemon_spawn()

    def test_callbacks(self):
        # For coverage.
        self.pm.pre_fork()
        self.pm.post_fork_child()
        self.pm.post_fork_parent()


def test_process_name_setproctitle_integration(tmp_path: Path) -> None:
    # NB: This test forks and then loads this module: we declare it so that it is inferred.
    import setproctitle  # noqa: F401

    buildroot = tmp_path / "buildroot"
    buildroot.mkdir()
    manager_name = "Bob"
    process_name = f"{manager_name} [{buildroot}]"
    metadata_base_dir = tmp_path / ".pids"
    metadata_base_dir.mkdir()

    subprocess.check_call(
        args=[
            sys.executable,
            "-c",
            dedent(
                f"""\
                from setproctitle import setproctitle as set_process_title

                from pants.pantsd.process_manager import ProcessManager


                set_process_title({process_name!r})
                pm = ProcessManager({manager_name!r}, metadata_base_dir="{metadata_base_dir}")
                pm.write_pid()
                pm.write_process_name()
                """
            ),
        ],
        env=dict(PYTHONPATH=os.pathsep.join(sys.path)),
    )

    pm = ProcessManager(manager_name, metadata_base_dir=str(metadata_base_dir))
    assert process_name == pm.process_name
