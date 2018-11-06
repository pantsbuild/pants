# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import re
from builtins import open, str

import mock

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.util.contextutil import temporary_dir
from pants.util.osutil import get_normalized_os_name
from pants_test.test_base import TestBase
from pants_test.testutils.py2_compat import assertRegex


class TestExceptionSink(TestBase):

  _default_log_dir = os.path.join(get_buildroot(), '.pants.d')

  def _gen_sink_subclass(self):
    # Avoid modifying global state by generating a subclass.
    class AnonymousSink(ExceptionSink): pass
    return AnonymousSink

  def test_default_log_location(self):
    # NB: get_buildroot() returns the temporary buildroot used for running this test, so we cheat
    # and assume we are being run from the buildroot.
    self.assertEqual(ExceptionSink._log_dir, self._default_log_dir)

  def test_reset_log_location(self):
    sink = self._gen_sink_subclass()

    with temporary_dir() as tmpdir:
      sink.reset_log_location(tmpdir)
      self.assertEqual(tmpdir, sink._log_dir)

  def test_set_invalid_log_location(self):
    self.assertFalse(os.path.isdir('/does/not/exist'))
    sink = self._gen_sink_subclass()
    err_rx = re.escape(
      "The provided exception sink path at '/does/not/exist' is not writable or could not be created: [Errno 13]")
    with self.assertRaisesRegexp(ExceptionSink.ExceptionSinkError, err_rx):
      sink.reset_log_location('/does/not/exist')


    # NB: This target is marked with 'platform_specific_behavior' because OSX errors out here at
    # creating a new directory with safe_mkdir(), Linux errors out trying to create the directory
    # for its log files with safe_open(). This may be due to differences in the filesystems.
    # TODO: figure out why we error out at different points here!
    if get_normalized_os_name() == 'darwin':
      err_rx = re.escape("The provided exception sink path at '/' is not writable or could not be created: [Errno 21] Is a directory: '/'.")
    else:
      err_rx = '.*'.join([
        re.escape("Error opening fatal error log streams for log location '/': [Errno 13] Permission denied: '/logs'"),
      ])
    with self.assertRaisesRegexp(ExceptionSink.ExceptionSinkError, err_rx):
      sink.reset_log_location('/')

  def test_log_exception(self):
    fake_process_title = 'fake_title'
    msg = 'XXX'
    sink = self._gen_sink_subclass()
    pid = os.getpid()

    with temporary_dir() as tmpdir:
      # Check that tmpdir exists, and log an exception into that directory.
      sink.reset_log_location(tmpdir)

      with mock.patch('setproctitle.getproctitle', autospec=True, spec_set=True) \
           as getproctitle_mock:
        getproctitle_mock.return_value = fake_process_title
        sink.log_exception(msg)
        getproctitle_mock.assert_called_once()

      # This should have created two log files, one specific to the current pid.
      self.assertEqual(os.listdir(tmpdir), ['logs'])

      cur_process_error_log_path = ExceptionSink.exceptions_log_path(for_pid=pid, in_dir=tmpdir)
      self.assertTrue(os.path.isfile(cur_process_error_log_path))

      shared_error_log_path = ExceptionSink.exceptions_log_path(in_dir=tmpdir)
      self.assertTrue(os.path.isfile(shared_error_log_path))
      # Ensure we're creating two separate files.
      self.assertNotEqual(cur_process_error_log_path, shared_error_log_path)

      # We only logged a single error, so the files should both contain only that single log entry.
      err_rx = """\
timestamp: ([^\n]+)
process title: {fake_process_title}
sys.argv: ([^\n]+)
pid: {pid}
{msg}
""".format(fake_process_title=re.escape(fake_process_title),
           pid=pid,
           msg=msg)
      with open(cur_process_error_log_path, 'r') as cur_pid_file:
        assertRegex(self, cur_pid_file.read(), err_rx)
      with open(shared_error_log_path, 'r') as shared_log_file:
        assertRegex(self, shared_log_file.read(), err_rx)

  def test_backup_logging_on_fatal_error(self):
    sink = self._gen_sink_subclass()
    with self.captured_logging(level=logging.ERROR) as captured:
      with temporary_dir() as tmpdir:
        sink.reset_log_location(tmpdir)
        with mock.patch.object(sink, '_try_write_with_flush', autospec=sink) as mock_write:
          mock_write.side_effect = ExceptionSink.ExceptionSinkError('fake write failure')
          sink.log_exception('XXX')
    errors = list(captured.errors())
    self.assertEqual(2, len(errors))

    def format_log_rx(log_file_type):
      return '.*'.join(re.escape(s) for s in [
        "pants.base.exception_sink: Error logging the message 'XXX' to the {log_file_type} file "
        "handle for".format(log_file_type=log_file_type),
        "at pid {pid}".format(pid=os.getpid()),
        "\nfake write failure",
      ])

    assertRegex(self, str(errors[0]), format_log_rx('pid-specific'))
    assertRegex(self, str(errors[1]), format_log_rx('shared'))
