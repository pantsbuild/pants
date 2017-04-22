# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import pstats
import shutil
import subprocess
import sys
import unittest
import zipfile

import mock

from pants.util.contextutil import (HardSystemExit, InvalidZipPath, Timer, environment_as,
                                    exception_logging, hard_exit_handler, maybe_profiled, open_zip,
                                    pushd, stdio_as, temporary_dir, temporary_file)


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

  def test_stdio_as(self):
    old_stdout, old_stderr, old_stdin = sys.stdout, sys.stderr, sys.stdin

    with stdio_as(stdout=1, stderr=2, stdin=3):
      self.assertEquals(sys.stdout, 1)
      self.assertEquals(sys.stderr, 2)
      self.assertEquals(sys.stdin, 3)

    self.assertEquals(sys.stdout, old_stdout)
    self.assertEquals(sys.stderr, old_stderr)
    self.assertEquals(sys.stdin, old_stdin)

  def test_stdio_as_stdin_default(self):
    old_stdout, old_stderr, old_stdin = sys.stdout, sys.stderr, sys.stdin

    with stdio_as(stdout=1, stderr=2):
      self.assertEquals(sys.stdout, 1)
      self.assertEquals(sys.stderr, 2)
      self.assertEquals(sys.stdin, old_stdin)

    self.assertEquals(sys.stdout, old_stdout)
    self.assertEquals(sys.stderr, old_stderr)

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
