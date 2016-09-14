# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import os
import subprocess
import sys
from contextlib import contextmanager

import mock
import psutil

from pants.pantsd.process_manager import (ProcessGroup, ProcessManager, ProcessMetadataManager,
                                          swallow_psutil_exceptions)
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_file_dump
from pants_test.base_test import BaseTest


PATCH_OPTS = dict(autospec=True, spec_set=True)


def fake_process(**kwargs):
  proc = mock.create_autospec(psutil.Process, spec_set=True)
  [setattr(getattr(proc, k), 'return_value', v) for k, v in kwargs.items()]
  return proc


class TestProcessGroup(BaseTest):
  def setUp(self):
    super(TestProcessGroup, self).setUp()
    self.pg = ProcessGroup('test', metadata_base_dir=self.subprocess_dir)

  def test_swallow_psutil_exceptions(self):
    with swallow_psutil_exceptions():
      raise psutil.NoSuchProcess('test')

  def test_iter_processes(self):
    with mock.patch('psutil.process_iter', **PATCH_OPTS) as mock_process_iter:
      mock_process_iter.return_value = [5, 4, 3, 2, 1]
      items = [item for item in self.pg.iter_processes()]
      self.assertEqual(items, [5, 4, 3, 2, 1])

  def test_iter_processes_filter_raises_psutil_exception(self):
    """If the filter triggers a psutil exception, skip the proc and continue."""
    with mock.patch('psutil.process_iter', **PATCH_OPTS) as mock_process_iter:
      def noop():
        return True
      def raises():
        raise psutil.NoSuchProcess('a_test')

      mock_process_iter.return_value = [
        noop,
        raises,
        noop
      ]

      items = [item for item in self.pg.iter_processes(proc_filter=lambda p: p())]
      self.assertEqual([noop, noop], items)

  def test_iter_processes_process_iter_raises_psutil_exception(self):
    """If psutil.process_iter raises the exception, silently stop iteration."""
    def id_or_raise(o):
      if isinstance(o, Exception):
        raise o
      else:
        return o
    with mock.patch('psutil.process_iter', **PATCH_OPTS) as mock_process_iter:
      mock_process_iter.return_value= (id_or_raise(i)
                                       for i in ['first',
                                                 psutil.NoSuchProcess('The Exception'),
                                                 'never seen'])

      items = [item for item in self.pg.iter_processes()]
      self.assertEqual(['first'], items)

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


class TestProcessMetadataManager(BaseTest):
  NAME = '_test_'
  TEST_KEY = 'TEST'
  TEST_VALUE = '300'
  TEST_VALUE_INT = 300
  BUILDROOT = '/mock_buildroot/'

  def setUp(self):
    super(TestProcessMetadataManager, self).setUp()
    self.pmm = ProcessMetadataManager(metadata_base_dir=self.subprocess_dir)

  def test_maybe_cast(self):
    self.assertIsNone(self.pmm._maybe_cast(None, int))
    self.assertEqual(self.pmm._maybe_cast('3333', int), 3333)
    self.assertEqual(self.pmm._maybe_cast('ssss', int), 'ssss')

  def test_get_metadata_dir_by_name(self):
    self.pmm = ProcessMetadataManager(metadata_base_dir=self.BUILDROOT)
    self.assertEqual(self.pmm._get_metadata_dir_by_name(self.NAME),
                     os.path.join(self.BUILDROOT, self.NAME))

  def test_maybe_init_metadata_dir_by_name(self):
    with mock.patch('pants.pantsd.process_manager.safe_mkdir', **PATCH_OPTS) as mock_mkdir:
      self.pmm._maybe_init_metadata_dir_by_name(self.NAME)
      mock_mkdir.assert_called_once_with(
        self.pmm._get_metadata_dir_by_name(self.NAME))

  def test_readwrite_metadata_by_name(self):
    with temporary_dir() as tmpdir, \
         mock.patch('pants.pantsd.process_manager.get_buildroot', return_value=tmpdir):
      self.pmm.write_metadata_by_name(self.NAME, self.TEST_KEY, self.TEST_VALUE)
      self.assertEqual(
        self.pmm.read_metadata_by_name(self.NAME, self.TEST_KEY),
        self.TEST_VALUE
      )
      self.assertEqual(
        self.pmm.read_metadata_by_name(self.NAME, self.TEST_KEY, int),
        self.TEST_VALUE_INT
      )

  def test_deadline_until(self):
    with self.assertRaises(self.pmm.Timeout):
      self.pmm._deadline_until(lambda: False, timeout=.1)

  def test_wait_for_file(self):
    with temporary_dir() as td:
      test_filename = os.path.join(td, 'test.out')
      safe_file_dump(test_filename, 'test')
      self.pmm._wait_for_file(test_filename, timeout=.1)

  def test_wait_for_file_timeout(self):
    with temporary_dir() as td:
      with self.assertRaises(self.pmm.Timeout):
        self.pmm._wait_for_file(os.path.join(td, 'non_existent_file'), timeout=.1)

  def test_await_metadata_by_name(self):
    with temporary_dir() as tmpdir, \
         mock.patch('pants.pantsd.process_manager.get_buildroot', return_value=tmpdir):
      self.pmm.write_metadata_by_name(self.NAME, self.TEST_KEY, self.TEST_VALUE)

      self.assertEquals(
        self.pmm.await_metadata_by_name(self.NAME, self.TEST_KEY, .1),
        self.TEST_VALUE
      )

  def test_purge_metadata(self):
    with mock.patch('pants.pantsd.process_manager.rm_rf') as mock_rm:
      self.pmm.purge_metadata_by_name(self.NAME)
    self.assertGreater(mock_rm.call_count, 0)

  def test_purge_metadata_error(self):
    with mock.patch('pants.pantsd.process_manager.rm_rf') as mock_rm:
      mock_rm.side_effect = OSError(errno.EACCES, os.strerror(errno.EACCES))
      with self.assertRaises(ProcessManager.MetadataError):
        self.pmm.purge_metadata_by_name(self.NAME)
    self.assertGreater(mock_rm.call_count, 0)


class TestProcessManager(BaseTest):
  def setUp(self):
    super(TestProcessManager, self).setUp()
    # N.B. We pass in `metadata_base_dir` here because ProcessManager (itself a non-task/non-
    # subsystem) depends on an initialized `GlobalOptions` subsystem for the value of
    # `--pants-subprocessdir` in the default case. This is normally provided by subsystem
    # dependencies in a typical pants run (and integration tests), but not in unit tests.
    # Thus, passing this parameter here short-circuits the subsystem-reliant path for the
    # purposes of unit testing without requiring adhoc subsystem initialization.
    self.pm = ProcessManager('test', metadata_base_dir=self.subprocess_dir)

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

  def test_get_subprocess_output(self):
    test_str = '333'
    self.assertEqual(self.pm.get_subprocess_output(['echo', '-n', test_str]), test_str)

  def test_get_subprocess_output_interleaved(self):
    cmd_payload = 'import sys; ' + 'sys.stderr.write("9"); sys.stdout.write("3"); ' * 3
    cmd = [sys.executable, '-c', cmd_payload]

    self.assertEqual(self.pm.get_subprocess_output(cmd), '333')
    self.assertEqual(self.pm.get_subprocess_output(cmd, ignore_stderr=False), '939393')
    self.assertEqual(self.pm.get_subprocess_output(cmd, stderr=subprocess.STDOUT), '939393')

  def test_get_subprocess_output_oserror_exception(self):
    with self.assertRaises(self.pm.ExecutionError):
      self.pm.get_subprocess_output(['i_do_not_exist'])

  def test_get_subprocess_output_failure_exception(self):
    with self.assertRaises(self.pm.ExecutionError):
      self.pm.get_subprocess_output(['false'])

  def test_await_pid(self):
    with mock.patch.object(ProcessManager, 'await_metadata_by_name') as mock_await:
      self.pm.await_pid(5)
    mock_await.assert_called_once_with(self.pm.name, 'pid', 5, mock.ANY)

  def test_await_socket(self):
    with mock.patch.object(ProcessManager, 'await_metadata_by_name') as mock_await:
      self.pm.await_socket(5)
    mock_await.assert_called_once_with(self.pm.name, 'socket', 5, mock.ANY)

  def test_write_pid(self):
    with mock.patch.object(ProcessManager, 'write_metadata_by_name') as mock_write:
      self.pm.write_pid(31337)
    mock_write.assert_called_once_with(self.pm.name, 'pid', '31337')

  def test_write_socket(self):
    with mock.patch.object(ProcessManager, 'write_metadata_by_name') as mock_write:
      self.pm.write_socket('/path/to/unix/socket')
    mock_write.assert_called_once_with(self.pm.name, 'socket', '/path/to/unix/socket')

  def test_write_named_socket(self):
    with mock.patch.object(ProcessManager, 'write_metadata_by_name') as mock_write:
      self.pm.write_named_socket('pailgun', '31337')
    mock_write.assert_called_once_with(self.pm.name, 'socket_pailgun', '31337')

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

  def test_is_alive_neg(self):
    with mock.patch.object(ProcessManager, '_as_process', **PATCH_OPTS) as mock_as_process:
      mock_as_process.return_value = None
      self.assertFalse(self.pm.is_alive())
      mock_as_process.assert_called_once_with(self.pm)

  def test_is_alive(self):
    with mock.patch.object(ProcessManager, '_as_process', **PATCH_OPTS) as mock_as_process:
      mock_as_process.return_value = fake_process(name='test', pid=3, status=psutil.STATUS_IDLE)
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

  def test_is_alive_extra_check(self):
    def extra_check(process):
      return False

    with mock.patch.object(ProcessManager, '_as_process', **PATCH_OPTS) as mock_as_process:
      mock_as_process.return_value = fake_process(name='test', pid=3, status=psutil.STATUS_IDLE)
      self.assertFalse(self.pm.is_alive(extra_check))
      mock_as_process.assert_called_with(self.pm)

  def test_purge_metadata_aborts(self):
    with mock.patch.object(ProcessManager, 'is_alive', return_value=True):
      with self.assertRaises(self.pm.MetadataError):
        self.pm.purge_metadata()

  def test_purge_metadata_alive_but_forced(self):
    with mock.patch.object(ProcessManager, 'is_alive', return_value=True), \
         mock.patch('pants.pantsd.process_manager.rm_rf') as mock_rm_rf:
      self.pm.purge_metadata(force=True)
      self.assertGreater(mock_rm_rf.call_count, 0)

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

  @contextmanager
  def mock_daemonize_context(self, chk_pre=True, chk_post_child=False, chk_post_parent=False):
    with mock.patch.object(ProcessManager, 'post_fork_parent', **PATCH_OPTS) as mock_post_parent, \
         mock.patch.object(ProcessManager, 'post_fork_child', **PATCH_OPTS) as mock_post_child, \
         mock.patch.object(ProcessManager, 'pre_fork', **PATCH_OPTS) as mock_pre, \
         mock.patch.object(ProcessManager, 'purge_metadata', **PATCH_OPTS) as mock_purge, \
         mock.patch('os._exit', **PATCH_OPTS), \
         mock.patch('os.chdir', **PATCH_OPTS), \
         mock.patch('os.setsid', **PATCH_OPTS), \
         mock.patch('os.waitpid', **PATCH_OPTS), \
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

  def test_callbacks(self):
    # For coverage.
    self.pm.pre_fork()
    self.pm.post_fork_child()
    self.pm.post_fork_parent()
