# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import unittest
from collections import namedtuple

import mock
import psutil

from pants.pantsd.process_manager import ProcessGroup, ProcessManager
from pants.util.contextutil import temporary_dir


PATCH_OPTS = dict(autospec=True, spec_set=True)


FakeProcess = namedtuple('Process', 'pid name')


class TestProcessGroup(unittest.TestCase):
  def setUp(self):
    self.pg = ProcessGroup('test')

  def test_swallow_psutil_exceptions(self):
    with self.pg._swallow_psutil_exceptions():
      raise psutil.NoSuchProcess('test')

  def test_iter_processes(self):
    with mock.patch('psutil.process_iter', **PATCH_OPTS) as mock_process_iter:
      mock_process_iter.return_value = [5, 4, 3, 2, 1]
      items = [item for item in self.pg.iter_processes()]
      self.assertEqual(items, [5, 4, 3, 2, 1])

  def test_iter_processes_filtered(self):
    with mock.patch('psutil.process_iter', **PATCH_OPTS) as mock_process_iter:
      mock_process_iter.return_value = [5, 4, 3, 2, 1]
      items = [item for item in self.pg.iter_processes(lambda x: x != 3)]
      self.assertEqual(items, [5, 4, 2, 1])

  def test_iter_instances(self):
    with mock.patch('psutil.process_iter', **PATCH_OPTS) as mock_process_iter:
      mock_process_iter.return_value = [FakeProcess(name='a_test', pid=3),
                                        FakeProcess(name='b_test', pid=4)]

      items = [item for item in self.pg.iter_instances()]
      self.assertEqual(len(items), 2)

      for item in items:
        self.assertIsInstance(item, ProcessManager)
        self.assertTrue('_test' in item.name)


class TestProcessManager(unittest.TestCase):
  def setUp(self):
    self.pm = ProcessManager('test')

  def test_maybe_cast(self):
    self.assertIsNone(self.pm._maybe_cast(None, int))
    self.assertEqual(self.pm._maybe_cast('3333', int), 3333)
    self.assertEqual(self.pm._maybe_cast('ssss', int), 'ssss')

  def test_readwrite_file(self):
    with temporary_dir() as td:
      test_filename = os.path.join(td, 'test.out')
      test_content = '3333'
      self.pm._write_file(test_filename, test_content)
      self.assertEqual(self.pm._read_file(test_filename), test_content)

  def test_as_process(self):
    sentinel = 3333
    with mock.patch('psutil.Process', **PATCH_OPTS) as mock_proc:
      mock_proc.return_value = sentinel
      self.pm._pid = sentinel
      self.assertEqual(self.pm.as_process(), sentinel)

  def test_as_process_none(self):
    self.assertEqual(self.pm.as_process(), None)

  def test_wait_for_file(self):
    with temporary_dir() as td:
      test_filename = os.path.join(td, 'test.out')
      self.pm._write_file(test_filename, 'test')
      self.pm._wait_for_file(test_filename, timeout=.1)

  def test_wait_for_file_timeout(self):
    with temporary_dir() as td:
      with self.assertRaises(self.pm.Timeout):
        self.pm._wait_for_file(os.path.join(td, 'non_existent_file'), timeout=.1)

  def test_await_pid(self):
    with temporary_dir() as td:
      test_filename = os.path.join(td, 'test.pid')
      self.pm._write_file(test_filename, '3333')

      with mock.patch.object(ProcessManager, 'get_pid_path', **PATCH_OPTS) as patched_pid:
        patched_pid.return_value = test_filename
        self.assertEqual(self.pm.await_pid(.1), 3333)

  def test_await_socket(self):
    with temporary_dir() as td:
      test_filename = os.path.join(td, 'test.sock')
      self.pm._write_file(test_filename, '3333')

      with mock.patch.object(ProcessManager, 'get_socket_path', **PATCH_OPTS) as patched_socket:
        patched_socket.return_value = test_filename
        self.assertEqual(self.pm.await_socket(.1), 3333)

  def test_maybe_init_metadata_dir(self):
    with mock.patch('pants.pantsd.process_manager.safe_mkdir', **PATCH_OPTS) as mock_mkdir:
      self.pm._maybe_init_metadata_dir()
      mock_mkdir.assert_called_once_with(self.pm.get_metadata_dir())

  def test_purge_metadata_abort(self):
    with mock.patch.object(ProcessManager, 'is_alive') as mock_alive:
      mock_alive.return_value = True
      with self.assertRaises(AssertionError):
        self.pm._purge_metadata()

  @mock.patch('pants.pantsd.process_manager.safe_delete')
  def test_purge_metadata(self, *args):
    with mock.patch.object(ProcessManager, 'is_alive') as mock_alive:
      with mock.patch('os.path.exists') as mock_exists:
        mock_alive.return_value = False
        mock_exists.return_value = True
        self.pm._purge_metadata()

  def test_get_metadata_dir(self):
    self.assertEqual(self.pm.get_metadata_dir(),
                     os.path.join(self.pm._buildroot, '.pids', self.pm._name))

  def test_get_pid_path(self):
    self.assertEqual(self.pm.get_pid_path(),
                     os.path.join(self.pm._buildroot, '.pids', self.pm._name, 'pid'))

  def test_get_socket_path(self):
    self.assertEqual(self.pm.get_socket_path(),
                     os.path.join(self.pm._buildroot, '.pids', self.pm._name, 'socket'))

  def test_write_pid(self):
    with mock.patch.object(ProcessManager, '_write_file') as patched_write:
      with mock.patch.object(ProcessManager, '_maybe_init_metadata_dir') as patched_init:
        self.pm.write_pid(3333)
        patched_write.assert_called_once_with(self.pm.get_pid_path(), '3333')
        patched_init.assert_called_once_with()

  def test_write_socket(self):
    with mock.patch.object(ProcessManager, '_write_file') as patched_write:
      with mock.patch.object(ProcessManager, '_maybe_init_metadata_dir') as patched_init:
        self.pm.write_socket(3333)
        patched_write.assert_called_once_with(self.pm.get_socket_path(), '3333')
        patched_init.assert_called_once_with()

  def test_get_pid(self):
    with mock.patch.object(ProcessManager, '_read_file', **PATCH_OPTS) as patched_pm:
      patched_pm.return_value = '3333'
      self.assertEqual(self.pm.get_pid(), 3333)

  def test_get_socket(self):
    with mock.patch.object(ProcessManager, '_read_file', **PATCH_OPTS) as patched_pm:
      patched_pm.return_value = '3333'
      self.assertEqual(self.pm.get_socket(), 3333)

  def test_is_alive_neg(self):
    with mock.patch('psutil.pid_exists', **PATCH_OPTS) as mock_psutil:
      mock_psutil.return_value = False
      self.assertFalse(self.pm.is_alive())
      mock_psutil.assert_called_once_with(None)

  def test_is_alive(self):
    with mock.patch('psutil.pid_exists', **PATCH_OPTS) as mock_psutil:
      mock_psutil.return_value = True
      self.pm._process = mock.Mock(status=psutil.STATUS_IDLE)
      self.assertTrue(self.pm.is_alive())
      mock_psutil.assert_called_once_with(None)

  def test_is_alive_zombie(self):
    with mock.patch('psutil.pid_exists', **PATCH_OPTS) as mock_psutil:
      mock_psutil.return_value = True
      self.pm._process = mock.Mock(status=psutil.STATUS_ZOMBIE)
      self.assertFalse(self.pm.is_alive())
      mock_psutil.assert_called_once_with(None)

  def test_is_alive_zombie_exception(self):
    with mock.patch('psutil.pid_exists', **PATCH_OPTS) as mock_psutil:
      with mock.patch.object(ProcessManager, 'as_process', **PATCH_OPTS) as mock_process:
        mock_psutil.return_value = True
        mock_process.side_effect = psutil.NoSuchProcess(0)
        self.assertFalse(self.pm.is_alive())
        mock_psutil.assert_called_once_with(None)

  def test_is_alive_stale_pid(self):
    with mock.patch('psutil.pid_exists', **PATCH_OPTS) as mock_psutil:
      mock_psutil.return_value = True
      self.pm._process_name = 'test'
      self.pm._process = mock.Mock()
      self.pm._process.configure_mock(status=psutil.STATUS_IDLE, name='not_test')
      self.assertFalse(self.pm.is_alive())
      mock_psutil.assert_called_once_with(None)

  def test_kill(self):
    with mock.patch('os.kill', **PATCH_OPTS) as mock_kill:
      self.pm.kill(0)
      mock_kill.assert_called_once_with(None, 0)

  def test_terminate(self):
    with mock.patch.object(ProcessManager, 'is_alive', **PATCH_OPTS) as mock_alive:
      with mock.patch('os.kill', **PATCH_OPTS):
        mock_alive.return_value = True
        with self.assertRaises(self.pm.NonResponsiveProcess):
          self.pm.terminate(kill_wait=.1, purge=False)

  def test_run_subprocess(self):
    test_str = '333'
    proc = self.pm.run_subprocess(['echo', test_str], stdout=subprocess.PIPE)
    proc.wait()
    self.assertEqual(proc.communicate()[0].strip(), test_str)

  @mock.patch('os.umask', **PATCH_OPTS)
  @mock.patch('os.chdir', **PATCH_OPTS)
  @mock.patch('os._exit', **PATCH_OPTS)
  @mock.patch('os.setsid', **PATCH_OPTS)
  def test_daemonize_parent(self, *args):
    with mock.patch('os.fork', **PATCH_OPTS) as mock_fork:
      mock_fork.side_effect = [1, 1]    # Simulate the parent.
      self.pm.daemonize(write_pid=False)
      # TODO(Kris Wilson): check that callbacks were called appropriately here and for daemon_spawn.

  @mock.patch('os.umask', **PATCH_OPTS)
  @mock.patch('os.chdir', **PATCH_OPTS)
  @mock.patch('os._exit', **PATCH_OPTS)
  @mock.patch('os.setsid', **PATCH_OPTS)
  def test_daemonize_child(self, *args):
    with mock.patch('os.fork', **PATCH_OPTS) as mock_fork:
      mock_fork.side_effect = [0, 0]    # Simulate the child.
      self.pm.daemonize(write_pid=False)

  @mock.patch('os.umask', **PATCH_OPTS)
  @mock.patch('os.chdir', **PATCH_OPTS)
  @mock.patch('os._exit', **PATCH_OPTS)
  @mock.patch('os.setsid', **PATCH_OPTS)
  def test_daemonize_child_parent(self, *args):
    with mock.patch('os.fork', **PATCH_OPTS) as mock_fork:
      mock_fork.side_effect = [0, 1]    # Simulate the childs parent.
      self.pm.daemonize(write_pid=False)

  @mock.patch('os.umask', **PATCH_OPTS)
  @mock.patch('os.chdir', **PATCH_OPTS)
  @mock.patch('os._exit', **PATCH_OPTS)
  @mock.patch('os.setsid', **PATCH_OPTS)
  def test_daemon_spawn_parent(self, *args):
    with mock.patch('os.fork', **PATCH_OPTS) as mock_fork:
      mock_fork.return_value = 1    # Simulate the parent.
      self.pm.daemon_spawn()

  @mock.patch('os.umask', **PATCH_OPTS)
  @mock.patch('os.chdir', **PATCH_OPTS)
  @mock.patch('os._exit', **PATCH_OPTS)
  @mock.patch('os.setsid', **PATCH_OPTS)
  def test_daemon_spawn_child(self, *args):
    with mock.patch('os.fork', **PATCH_OPTS) as mock_fork:
      mock_fork.return_value = 0    # Simulate the child.
      self.pm.daemon_spawn()
