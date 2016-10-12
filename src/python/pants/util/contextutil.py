# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import shutil
import sys
import tempfile
import time
import uuid
import zipfile
from contextlib import closing, contextmanager

from colors import green
from six import string_types

from pants.util.dirutil import safe_delete
from pants.util.tarutil import TarFile


@contextmanager
def environment_as(**kwargs):
  """Update the environment to the supplied values, for example:

  with environment_as(PYTHONPATH='foo:bar:baz',
                      PYTHON='/usr/bin/python2.6'):
    subprocess.Popen(foo).wait()
  """
  new_environment = kwargs
  old_environment = {}

  def setenv(key, val):
    if val is not None:
      os.environ[key] = val
    else:
      if key in os.environ:
        del os.environ[key]

  for key, val in new_environment.items():
    old_environment[key] = os.environ.get(key)
    setenv(key, val)
  try:
    yield
  finally:
    for key, val in old_environment.items():
      setenv(key, val)


@contextmanager
def stdio_as(stdout, stderr, stdin=None):
  """Redirect sys.{stdout, stderr, stdin} to alternate file-like objects."""
  old_stdout, sys.stdout = sys.stdout, stdout
  old_stderr, sys.stderr = sys.stderr, stderr
  if stdin:
    old_stdin, sys.stdin = sys.stdin, stdin
  yield
  sys.stdout, sys.stderr = old_stdout, old_stderr
  if stdin:
    sys.stdin = old_stdin


@contextmanager
def temporary_dir(root_dir=None, cleanup=True, suffix=str(), permissions=None, prefix=tempfile.template):
  """
    A with-context that creates a temporary directory.

    :API: public

    You may specify the following keyword args:
    :param string root_dir: The parent directory to create the temporary directory.
    :param bool cleanup: Whether or not to clean up the temporary directory.
    :param int permissions: If provided, sets the directory permissions to this mode.
  """
  path = tempfile.mkdtemp(dir=root_dir, suffix=suffix, prefix=prefix)

  try:
    if permissions is not None:
      os.chmod(path, permissions)
    yield path
  finally:
    if cleanup:
      shutil.rmtree(path, ignore_errors=True)


@contextmanager
def temporary_file_path(root_dir=None, cleanup=True, suffix='', permissions=None):
  """
    A with-context that creates a temporary file and returns its path.

    :API: public

    You may specify the following keyword args:
    :param str root_dir: The parent directory to create the temporary file.
    :param bool cleanup: Whether or not to clean up the temporary file.
  """
  with temporary_file(root_dir, cleanup=cleanup, suffix=suffix, permissions=permissions) as fd:
    fd.close()
    yield fd.name


@contextmanager
def temporary_file(root_dir=None, cleanup=True, suffix='', permissions=None):
  """
    A with-context that creates a temporary file and returns a writeable file descriptor to it.

    You may specify the following keyword args:
    :param str root_dir: The parent directory to create the temporary file.
    :param bool cleanup: Whether or not to clean up the temporary file.
    :param str suffix: If suffix is specified, the file name will end with that suffix.
                       Otherwise there will be no suffix.
                       mkstemp() does not put a dot between the file name and the suffix;
                       if you need one, put it at the beginning of suffix.
                       See :py:class:`tempfile.NamedTemporaryFile`.
    :param int permissions: If provided, sets the file to use these permissions.
  """
  with tempfile.NamedTemporaryFile(suffix=suffix, dir=root_dir, delete=False) as fd:
    try:
      if permissions is not None:
        os.chmod(fd.name, permissions)
      yield fd
    finally:
      if cleanup:
        safe_delete(fd.name)


@contextmanager
def safe_file(path, suffix=None, cleanup=True):
  """A with-context that copies a file, and copies the copy back to the original file on success.

  This is useful for doing work on a file but only changing its state on success.

  :param str suffix: Use this suffix to create the copy. Otherwise use a random string.
  :param bool cleanup: Whether or not to clean up the copy.
  """
  safe_path = '{0}.{1}'.format(path, suffix or uuid.uuid4())
  if os.path.exists(path):
    shutil.copy(path, safe_path)
  try:
    yield safe_path
    if cleanup:
      shutil.move(safe_path, path)
    else:
      shutil.copy(safe_path, path)
  finally:
    if cleanup:
      safe_delete(safe_path)


@contextmanager
def pushd(directory):
  """
    A with-context that encapsulates pushd/popd.
  """
  cwd = os.getcwd()
  os.chdir(directory)
  try:
    yield directory
  finally:
    os.chdir(cwd)


@contextmanager
def open_zip(path_or_file, *args, **kwargs):
  """
    A with-context for zip files.  Passes through positional and kwargs to zipfile.ZipFile.

    :API: public
  """
  try:
    allowZip64 = kwargs.pop('allowZip64', True)
    zf = zipfile.ZipFile(path_or_file, *args, allowZip64=allowZip64, **kwargs)
  except zipfile.BadZipfile as bze:
    raise zipfile.BadZipfile("Bad Zipfile {0}: {1}".format(path_or_file, bze))
  try:
    yield zf
  finally:
    zf.close()


@contextmanager
def open_tar(path_or_file, *args, **kwargs):
  """
    A with-context for tar files.  Passes through positional and kwargs to tarfile.open.

    If path_or_file is a file, caller must close it separately.
  """
  (path, fileobj) = ((path_or_file, None) if isinstance(path_or_file, string_types)
                     else (None, path_or_file))
  with closing(TarFile.open(path, *args, fileobj=fileobj, **kwargs)) as tar:
    yield tar


class Timer(object):
  """Very basic with-context to time operations

  Example usage:
    >>> from pants.util.contextutil import Timer
    >>> with Timer() as timer:
    ...   time.sleep(2)
    ...
    >>> timer.elapsed
    2.0020849704742432

  """

  def __init__(self, clock=time):
    self._clock = clock

  def __enter__(self):
    self.start = self._clock.time()
    self.finish = None
    return self

  @property
  def elapsed(self):
    if self.finish:
      return self.finish - self.start
    else:
      return self._clock.time() - self.start

  def __exit__(self, typ, val, traceback):
    self.finish = self._clock.time()


@contextmanager
def exception_logging(logger, msg):
  """Provides exception logging via `logger.exception` for a given block of code.

  :param logging.Logger logger: The `Logger` instance to use for logging.
  :param string msg: The message to emit before `logger.exception` emits the traceback.
  """
  try:
    yield
  except Exception:
    logger.exception(msg)
    raise


@contextmanager
def maybe_profiled(profile_path):
  """A profiling context manager.

  :param string profile_path: The path to write profile information to. If `None`, this will no-op.
  """
  if not profile_path:
    yield
    return

  import cProfile
  profiler = cProfile.Profile()
  try:
    profiler.enable()
    yield
  finally:
    profiler.disable()
    profiler.dump_stats(profile_path)
    view_cmd = green('gprof2dot -f pstats {path} | dot -Tpng -o {path}.png && open {path}.png'
                     .format(path=profile_path))
    logging.getLogger().info(
      'Dumped profile data to: {}\nUse e.g. {} to render and view.'.format(profile_path, view_cmd)
    )


class HardSystemExit(SystemExit):
  """A SystemExit subclass that incurs an os._exit() via special handling."""


@contextmanager
def hard_exit_handler():
  """An exit helper for the daemon/fork'd context that provides for deferred os._exit(0) calls."""
  try:
    yield
  except HardSystemExit:
    os._exit(0)
