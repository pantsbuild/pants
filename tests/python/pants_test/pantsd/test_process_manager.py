# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import os
import unittest
from contextlib import contextmanager

import mock
import psutil

from pants.pantsd.process_manager import ProcessGroup, ProcessManager, swallow_psutil_exceptions
from pants.util.contextutil import temporary_dir


PATCH_OPTS = dict(autospec=True, spec_set=True)


def fake_process(**kwargs):
  proc = mock.create_autospec(psutil.Process, spec_set=True)
  [setattr(getattr(proc, k), 'return_value', v) for k, v in kwargs.items()]
  return proc


class TestProcessGroup(unittest.TestCase):
  def setUp(self):
    self.pg = ProcessGroup('test')

  def test_swallow_psutil_exceptions(self):
    with swallow_psutil_exceptions():
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
      mock_process_iter.return_value = [
        fake_process(name='a_test', pid=3, status=psutil.STATUS_IDLE),
        fake_process(name='b_test', pid=4, status=psutil.STATUS_IDLE)
      ]

      items = [item for item in self.pg.iter_instances()]
      self.assertEqual(len(items), 2)

      for item in items:
        self.assertIsInstance(item, ProcessManager)
        self.assertTrue('_test' in item.name)


class TestProcessManager(unittest.TestCase):
  def setUp(self):
    self.pm = ProcessManager('test')

  def test_callbacks(self):
    # For coverage.
    self.pm.pre_fork()
    self.pm.post_fork_child()
    self.pm.post_fork_parent()

  def test_process_properties(self):
    with mock.patch.object(ProcessManager, '_as_process', **PATCH_OPTS) as mock_as_process:
      mock_as_process.return_value = fake_process(name='name',
                                                  cmdline=['cmd', 'line'],
                                                  status='status')
      self.assertEqual(self.pm.cmdline, ['cmd', 'line'])
      self.assertEqual(self.pm.cmd, 'cmd')

  def test_process_properties_cmd_indexing(self):
    with mock.patch.object(ProcessManager, '_as_process', **PATCH_OPTS) as mock_as_process:
      mock_as_process.return_value = fake_process(cmdline='')
      self.assertEqual(self.pm.cmd, None)

  def test_process_properties_none(self):
    with mock.patch.object(ProcessManager, '_as_process', **PATCH_OPTS) as mock_asproc:
      mock_asproc.return_value = None
      self.assertEqual(self.pm.cmdline, None)
      self.assertEqual(self.pm.cmd, None)

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
      self.assertEqual(self.pm._as_process(), sentinel)

  def test_as_process_no_pid(self):
    fake_pid = 3
    with mock.patch('psutil.Process', **PATCH_OPTS) as mock_proc:
      mock_proc.side_effect = psutil.NoSuchProcess(fake_pid)
      self.pm._pid = fake_pid
      with self.assertRaises(psutil.NoSuchProcess):
        self.pm._as_process()

  def test_as_process_none(self):
    self.assertEqual(self.pm._as_process(), None)

  def test_deadline_until(self):
    with self.assertRaises(self.pm.Timeout):
      self.pm._deadline_until(lambda: False, timeout=.1)

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
        self.pm.purge_metadata()

  def test_purge_metadata(self):
    with mock.patch.object(ProcessManager, 'is_alive') as mock_alive, \
         mock.patch('pants.pantsd.process_manager.rm_rf') as mock_rm_rf:
      mock_alive.return_value = False
      self.pm.purge_metadata()
      mock_rm_rf.assert_called_once_with(self.pm.get_metadata_dir())

  def test_purge_metadata_alive_but_forced(self):
    with mock.patch.object(ProcessManager, 'is_alive') as mock_alive, \
         mock.patch('pants.pantsd.process_manager.rm_rf') as mock_rm_rf:
      mock_alive.return_value = True
      self.pm.purge_metadata(force=True)
      mock_rm_rf.assert_called_once_with(self.pm.get_metadata_dir())

  def test_purge_metadata_metadata_error(self):
    with mock.patch.object(ProcessManager, 'is_alive') as mock_alive, \
         mock.patch('pants.pantsd.process_manager.rm_rf') as mock_rm_rf:
      mock_alive.return_value = False
      mock_rm_rf.side_effect = OSError(errno.EACCES, os.strerror(errno.EACCES))
      with self.assertRaises(ProcessManager.MetadataError):
        self.pm.purge_metadata()

  def test_get_metadata_dir(self):
    self.assertEqual(self.pm.get_metadata_dir(),
                     os.path.join(self.pm._buildroot, '.pids', self.pm._name))

  def test_get_pid_path(self):
    self.assertEqual(self.pm.get_pid_path(),
                     os.path.join(self.pm._buildroot, '.pids', self.pm._name, 'pid'))

  def test_get_socket_path(self):
    self.assertEqual(self.pm.get_socket_path(),
                     os.path.join(self.pm._buildroot, '.pids', self.pm._name, 'socket'))

  def test_get_named_socket_path(self):
    self.assertEqual(self.pm._get_named_socket_path('test'),
                     os.path.join(self.pm._buildroot, '.pids', self.pm._name, 'socket_test'))

  def test_write_pid(self):
    with mock.patch.object(ProcessManager, '_write_file') as patched_write, \
         mock.patch.object(ProcessManager, '_maybe_init_metadata_dir') as patched_init:
      self.pm.write_pid(3333)
      patched_write.assert_called_once_with(self.pm.get_pid_path(), '3333')
      patched_init.assert_called_once_with()

  def test_write_socket(self):
    with mock.patch.object(ProcessManager, '_write_file') as patched_write, \
         mock.patch.object(ProcessManager, '_maybe_init_metadata_dir') as patched_init:
      self.pm.write_socket(3333)
      patched_write.assert_called_once_with(self.pm.get_socket_path(), '3333')
      patched_init.assert_called_once_with()

  def test_write_named_socket(self):
    with mock.patch.object(ProcessManager, '_write_file') as patched_write, \
         mock.patch.object(ProcessManager, '_maybe_init_metadata_dir') as patched_init:
      self.pm.write_named_socket('pailgun', 3333)
      patched_write.assert_called_once_with(self.pm._get_named_socket_path('pailgun'), '3333')
      patched_init.assert_called_once_with()

  def test_get_pid(self):
    with mock.patch.object(ProcessManager, '_read_file', **PATCH_OPTS) as patched_read_file:
      patched_read_file.return_value = '3333'
      self.assertEqual(self.pm._get_pid(), 3333)

  def test_get_socket(self):
    with mock.patch.object(ProcessManager, '_read_file', **PATCH_OPTS) as patched_read_file:
      patched_read_file.return_value = '3333'
      self.assertEqual(self.pm._get_socket(), 3333)

  def test_get_named_socket(self):
    with mock.patch.object(ProcessManager, '_read_file', **PATCH_OPTS) as patched_read_file:
      patched_read_file.return_value = '3333'
      self.assertEqual(self.pm.get_named_socket('test'), 3333)

  def test_is_alive_neg(self):
    with mock.patch.object(ProcessManager, '_as_process', **PATCH_OPTS) as mock_as_process:
      mock_as_process.return_value = None
      self.assertFalse(self.pm.is_alive())
      mock_as_process.assert_called_once_with(self.pm)

  def test_is_alive(self):
    with mock.patch.object(ProcessManager, '_as_process', **PATCH_OPTS) as mock_as_process:
      mock_as_process.return_value = fake_process(name='test', pid=3, status=psutil.STATUS_IDLE)
      self.pm._process = mock.Mock(status=psutil.STATUS_IDLE)
      self.assertTrue(self.pm.is_alive())
      mock_as_process.assert_called_with(self.pm)

  def test_is_alive_zombie(self):
    with mock.patch.object(ProcessManager, '_as_process', **PATCH_OPTS) as mock_as_process:
      mock_as_process.return_value = fake_process(name='test', pid=3, status=psutil.STATUS_ZOMBIE)
      self.assertFalse(self.pm.is_alive())
      mock_as_process.assert_called_with(self.pm)

  def test_is_alive_zombie_exception(self):
    with mock.patch.object(ProcessManager, '_as_process', **PATCH_OPTS) as mock_as_process:
      mock_as_process.side_effect = psutil.NoSuchProcess(0)
      self.assertFalse(self.pm.is_alive())
      mock_as_process.assert_called_with(self.pm)

  def test_is_alive_stale_pid(self):
    with mock.patch.object(ProcessManager, '_as_process', **PATCH_OPTS) as mock_as_process:
      mock_as_process.return_value = fake_process(name='not_test', pid=3, status=psutil.STATUS_IDLE)
      self.pm._process_name = 'test'
      self.assertFalse(self.pm.is_alive())
      mock_as_process.assert_called_with(self.pm)

  def test_kill(self):
    with mock.patch('os.kill', **PATCH_OPTS) as mock_kill:
      self.pm._pid = 42
      self.pm._kill(0)
      mock_kill.assert_called_once_with(42, 0)

  def test_kill_no_pid(self):
    with mock.patch('os.kill', **PATCH_OPTS) as mock_kill:
      self.pm._kill(0)
      self.assertFalse(mock_kill.called, 'If we have no pid, kills should noop gracefully.')

  @contextmanager
  def setup_terminate(self):
    with mock.patch.object(ProcessManager, '_kill', **PATCH_OPTS) as mock_kill, \
         mock.patch.object(ProcessManager, 'is_alive', **PATCH_OPTS) as mock_alive, \
         mock.patch.object(ProcessManager, 'purge_metadata', **PATCH_OPTS) as mock_purge:
      yield mock_kill, mock_alive, mock_purge
      self.assertGreater(mock_alive.call_count, 0)

  def test_terminate_quick_death(self):
    with self.setup_terminate() as (mock_kill, mock_alive, mock_purge):
      mock_kill.side_effect = OSError('oops')
      mock_alive.side_effect = [True, False]
      self.pm.terminate(kill_wait=.1)
      self.assertEqual(mock_kill.call_count, 1)
      self.assertEqual(mock_purge.call_count, 1)

  def test_terminate_quick_death_no_purge(self):
    with self.setup_terminate() as (mock_kill, mock_alive, mock_purge):
      mock_kill.side_effect = OSError('oops')
      mock_alive.side_effect = [True, False]
      self.pm.terminate(purge=False, kill_wait=.1)
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
      with self.assertRaises(self.pm.NonResponsiveProcess):
        self.pm.terminate(kill_wait=.1, purge=True)
      self.assertEqual(mock_kill.call_count, len(ProcessManager.KILL_CHAIN))
      self.assertEqual(mock_purge.call_count, 0)

  def test_get_subprocess_output(self):
    test_str = '333'
    self.assertEqual(self.pm.get_subprocess_output(['echo', '-n', test_str]), test_str)

  def test_get_subprocess_output_oserror_exception(self):
    with self.assertRaises(self.pm.ExecutionError):
      self.pm.get_subprocess_output(['i_do_not_exist'])

  def test_get_subprocess_output_failure_exception(self):
    with self.assertRaises(self.pm.ExecutionError):
      self.pm.get_subprocess_output(['false'])

  @contextmanager
  def mock_daemonize_context(self, chk_pre=True, chk_post_child=False, chk_post_parent=False):
    with mock.patch.object(ProcessManager, 'post_fork_parent', **PATCH_OPTS) as mock_post_parent, \
         mock.patch.object(ProcessManager, 'post_fork_child', **PATCH_OPTS) as mock_post_child, \
         mock.patch.object(ProcessManager, 'pre_fork', **PATCH_OPTS) as mock_pre, \
         mock.patch.object(ProcessManager, 'purge_metadata', **PATCH_OPTS) as mock_purge, \
         mock.patch('os.chdir', **PATCH_OPTS), \
         mock.patch('os._exit', **PATCH_OPTS), \
         mock.patch('os.setsid', **PATCH_OPTS), \
         mock.patch('os.fork', **PATCH_OPTS) as mock_fork:
      yield mock_fork

      mock_purge.assert_called_once_with(self.pm)
      if chk_pre: mock_pre.assert_called_once_with(self.pm)
      if chk_post_child: mock_post_child.assert_called_once_with(self.pm)
      if chk_post_parent: mock_post_parent.assert_called_once_with(self.pm)

  def test_daemonize_parent(self):
    with self.mock_daemonize_context() as mock_fork:
      mock_fork.side_effect = [1, 1]    # Simulate the parent.
      self.pm.daemonize(write_pid=False)

  def test_daemonize_child(self):
    with self.mock_daemonize_context(chk_post_child=True) as mock_fork:
      mock_fork.side_effect = [0, 0]    # Simulate the child.
      self.pm.daemonize(write_pid=False)

  def test_daemonize_child_parent(self):
    with self.mock_daemonize_context(chk_post_parent=True) as mock_fork:
      mock_fork.side_effect = [0, 1]    # Simulate the childs parent.
      self.pm.daemonize(write_pid=False)

  def test_daemon_spawn_parent(self):
    with self.mock_daemonize_context(chk_post_parent=True) as mock_fork:
      mock_fork.return_value = 1        # Simulate the parent.
      self.pm.daemon_spawn()

  def test_daemon_spawn_child(self):
    with self.mock_daemonize_context(chk_post_child=True) as mock_fork:
      mock_fork.return_value = 0        # Simulate the child.
      self.pm.daemon_spawn()
