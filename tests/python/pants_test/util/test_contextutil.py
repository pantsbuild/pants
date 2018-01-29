# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import pstats
import shutil
import signal
import sys
import unittest
import uuid
import zipfile
from contextlib import contextmanager

import mock

from pants.util.contextutil import (HardSystemExit, InvalidZipPath, Timer, environment_as,
                                    exception_logging, hard_exit_handler, maybe_profiled, open_zip,
                                    pushd, signal_handler_as, stdio_as, temporary_dir,
                                    temporary_file)
from pants.util.process_handler import subprocess


PATCH_OPTS = dict(autospec=True, spec_set=True)


class ContextutilTest(unittest.TestCase):

  def test_empty_environment(self):
    with environment_as():
      pass

  def test_override_single_variable(self):
    with temporary_file() as output:
      # test that the override takes place
      with environment_as(HORK='BORK'):
        subprocess.Popen([sys.executable, '-c', 'import os; print(os.environ["HORK"])'],
                         stdout=output).wait()
        output.seek(0)
        self.assertEquals('BORK\n', output.read())

      # test that the variable is cleared
      with temporary_file() as new_output:
        subprocess.Popen([sys.executable, '-c', 'import os; print("HORK" in os.environ)'],
                         stdout=new_output).wait()
        new_output.seek(0)
        self.assertEquals('False\n', new_output.read())

  def test_environment_negation(self):
    with temporary_file() as output:
      with environment_as(HORK='BORK'):
        with environment_as(HORK=None):
          # test that the variable is cleared
          subprocess.Popen([sys.executable, '-c', 'import os; print("HORK" in os.environ)'],
                           stdout=output).wait()
          output.seek(0)
          self.assertEquals('False\n', output.read())

  def test_simple_pushd(self):
    pre_cwd = os.getcwd()
    with temporary_dir() as tempdir:
      with pushd(tempdir) as path:
        self.assertEquals(tempdir, path)
        self.assertEquals(os.path.realpath(tempdir), os.getcwd())
      self.assertEquals(pre_cwd, os.getcwd())
    self.assertEquals(pre_cwd, os.getcwd())

  def test_nested_pushd(self):
    pre_cwd = os.getcwd()
    with temporary_dir() as tempdir1:
      with pushd(tempdir1):
        self.assertEquals(os.path.realpath(tempdir1), os.getcwd())
        with temporary_dir(root_dir=tempdir1) as tempdir2:
          with pushd(tempdir2):
            self.assertEquals(os.path.realpath(tempdir2), os.getcwd())
          self.assertEquals(os.path.realpath(tempdir1), os.getcwd())
        self.assertEquals(os.path.realpath(tempdir1), os.getcwd())
      self.assertEquals(pre_cwd, os.getcwd())
    self.assertEquals(pre_cwd, os.getcwd())

  def test_temporary_file_no_args(self):
    with temporary_file() as fp:
      self.assertTrue(os.path.exists(fp.name), 'Temporary file should exist within the context.')
    self.assertTrue(os.path.exists(fp.name) == False,
                    'Temporary file should not exist outside of the context.')

  def test_temporary_file_without_cleanup(self):
    with temporary_file(cleanup=False) as fp:
      self.assertTrue(os.path.exists(fp.name), 'Temporary file should exist within the context.')
    self.assertTrue(os.path.exists(fp.name),
                    'Temporary file should exist outside of context if cleanup=False.')
    os.unlink(fp.name)

  def test_temporary_file_within_other_dir(self):
    with temporary_dir() as path:
      with temporary_file(root_dir=path) as f:
        self.assertTrue(os.path.realpath(f.name).startswith(os.path.realpath(path)),
                        'file should be created in root_dir if specified.')

  def test_temporary_dir_no_args(self):
    with temporary_dir() as path:
      self.assertTrue(os.path.exists(path), 'Temporary dir should exist within the context.')
      self.assertTrue(os.path.isdir(path), 'Temporary dir should be a dir and not a file.')
    self.assertFalse(os.path.exists(path), 'Temporary dir should not exist outside of the context.')

  def test_temporary_dir_without_cleanup(self):
    with temporary_dir(cleanup=False) as path:
      self.assertTrue(os.path.exists(path), 'Temporary dir should exist within the context.')
    self.assertTrue(os.path.exists(path),
                    'Temporary dir should exist outside of context if cleanup=False.')
    shutil.rmtree(path)

  def test_temporary_dir_with_root_dir(self):
    with temporary_dir() as path1:
      with temporary_dir(root_dir=path1) as path2:
        self.assertTrue(os.path.realpath(path2).startswith(os.path.realpath(path1)),
                        'Nested temporary dir should be created within outer dir.')

  def test_timer(self):

    class FakeClock(object):

      def __init__(self):
        self._time = 0.0

      def time(self):
        ret = self._time
        self._time += 0.0001  # Force a little time to elapse.
        return ret

      def sleep(self, duration):
        self._time += duration

    clock = FakeClock()

    # Note: to test with the real system clock, use this instead:
    # import time
    # clock = time

    with Timer(clock=clock) as t:
      self.assertLess(t.start, clock.time())
      self.assertGreater(t.elapsed, 0)
      clock.sleep(0.1)
      self.assertGreater(t.elapsed, 0.1)
      clock.sleep(0.1)
      self.assertTrue(t.finish is None)
    self.assertGreater(t.elapsed, 0.2)
    self.assertLess(t.finish, clock.time())

  def test_open_zipDefault(self):
    with temporary_dir() as tempdir:
      with open_zip(os.path.join(tempdir, 'test'), 'w') as zf:
        self.assertTrue(zf._allowZip64)

  def test_open_zipTrue(self):
    with temporary_dir() as tempdir:
      with open_zip(os.path.join(tempdir, 'test'), 'w', allowZip64=True) as zf:
        self.assertTrue(zf._allowZip64)

  def test_open_zipFalse(self):
    with temporary_dir() as tempdir:
      with open_zip(os.path.join(tempdir, 'test'), 'w', allowZip64=False) as zf:
        self.assertFalse(zf._allowZip64)

  def test_open_zip_raises_exception_on_falsey_paths(self):
    falsey = (None, '', False)
    for invalid in falsey:
      with self.assertRaises(InvalidZipPath):
        open_zip(invalid).gen.next()

  def test_open_zip_returns_realpath_on_badzipfile(self):
    # In case of file corruption, deleting a Pants-constructed symlink would not resolve the error.
    with temporary_file() as not_zip:
      with temporary_dir() as tempdir:
        file_symlink = os.path.join(tempdir, 'foo')
        os.symlink(not_zip.name, file_symlink)
        self.assertEquals(os.path.realpath(file_symlink), os.path.realpath(not_zip.name))
        with self.assertRaisesRegexp(zipfile.BadZipfile, r'{}'.format(not_zip.name)):
          open_zip(file_symlink).gen.next()

  @contextmanager
  def _stdio_as_tempfiles(self):
    """Harness to replace `sys.std*` with tempfiles.

    Validates that all files are read/written/flushed correctly, and acts as a
    contextmanager to allow for recursive tests.
    """

    # Prefix contents written within this instance with a unique string to differentiate
    # them from other instances.
    uuid_str = str(uuid.uuid4())
    def u(string):
      return '{}#{}'.format(uuid_str, string)
    stdin_data = u('stdio')
    stdout_data = u('stdout')
    stderr_data = u('stderr')

    with temporary_file() as tmp_stdin,\
         temporary_file() as tmp_stdout,\
         temporary_file() as tmp_stderr:
      print(stdin_data, file=tmp_stdin)
      tmp_stdin.seek(0)
      # Read prepared content from stdin, and write content to stdout/stderr.
      with stdio_as(stdout_fd=tmp_stdout.fileno(),
                    stderr_fd=tmp_stderr.fileno(),
                    stdin_fd=tmp_stdin.fileno()):
        self.assertEquals(sys.stdin.fileno(), 0)
        self.assertEquals(sys.stdout.fileno(), 1)
        self.assertEquals(sys.stderr.fileno(), 2)

        self.assertEquals(stdin_data, sys.stdin.read().strip())
        print(stdout_data, file=sys.stdout)
        yield
        print(stderr_data, file=sys.stderr)

      tmp_stdout.seek(0)
      tmp_stderr.seek(0)
      self.assertEquals(stdout_data, tmp_stdout.read().strip())
      self.assertEquals(stderr_data, tmp_stderr.read().strip())

  def test_stdio_as(self):
    self.assertTrue(sys.stderr.fileno() > 2,
                    "Expected a pseudofile as stderr, got: {}".format(sys.stderr))
    old_stdout, old_stderr, old_stdin = sys.stdout, sys.stderr, sys.stdin

    # The first level tests that when `sys.std*` are file-likes (in particular, the ones set up in
    # pytest's harness) rather than actual files, we stash and restore them properly.
    with self._stdio_as_tempfiles():
      # The second level stashes the first level's actual file objects and then re-opens them.
      with self._stdio_as_tempfiles():
        pass

      # Validate that after the second level completes, the first level still sees valid
      # fds on `sys.std*`.
      self.assertEquals(sys.stdin.fileno(), 0)
      self.assertEquals(sys.stdout.fileno(), 1)
      self.assertEquals(sys.stderr.fileno(), 2)

    self.assertEquals(sys.stdout, old_stdout)
    self.assertEquals(sys.stderr, old_stderr)
    self.assertEquals(sys.stdin, old_stdin)

  def test_stdio_as_dev_null(self):
    # Capture output to tempfiles.
    with self._stdio_as_tempfiles():
      # Read/write from/to `/dev/null`, which will be validated by the harness as not
      # affecting the tempfiles.
      with stdio_as(stdout_fd=-1, stderr_fd=-1, stdin_fd=-1):
        self.assertEquals(b'', sys.stdin.read())
        print('garbage', file=sys.stdout)
        print('garbage', file=sys.stderr)

  def test_signal_handler_as(self):
    mock_initial_handler = 1
    mock_new_handler = 2
    with mock.patch('signal.signal', **PATCH_OPTS) as mock_signal:
      mock_signal.return_value = mock_initial_handler
      try:
        with signal_handler_as(signal.SIGUSR2, mock_new_handler):
          raise NotImplementedError('blah')
      except NotImplementedError:
        pass
    self.assertEquals(mock_signal.call_count, 2)
    mock_signal.assert_has_calls([
      mock.call(signal.SIGUSR2, mock_new_handler),
      mock.call(signal.SIGUSR2, mock_initial_handler)
    ])

  def test_permissions(self):
    with temporary_file(permissions=0700) as f:
      self.assertEquals(0700, os.stat(f.name)[0] & 0777)

    with temporary_dir(permissions=0644) as path:
      self.assertEquals(0644, os.stat(path)[0] & 0777)

  def test_exception_logging(self):
    fake_logger = mock.Mock()

    with self.assertRaises(AssertionError):
      with exception_logging(fake_logger, 'error!'):
        assert True is False

    fake_logger.exception.assert_called_once_with('error!')

  def test_maybe_profiled(self):
    with temporary_dir() as td:
      profile_path = os.path.join(td, 'profile.prof')

      with maybe_profiled(profile_path):
        for _ in range(5):
          print('test')

      # Ensure the profile data was written.
      self.assertTrue(os.path.exists(profile_path))

      # Ensure the profile data is valid.
      pstats.Stats(profile_path).print_stats()

  def test_hard_exit_handler(self):
    with mock.patch('os._exit', **PATCH_OPTS) as mock_exit:
      with hard_exit_handler():
        raise HardSystemExit()

    mock_exit.assert_called_once_with(0)
