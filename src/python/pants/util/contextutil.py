# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import shutil
import signal
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


class InvalidZipPath(ValueError):
  """Indicates a bad zip file path."""


@contextmanager
def environment_as(**kwargs):
  """Update the environment to the supplied values, for example:

  with environment_as(PYTHONPATH='foo:bar:baz',
                      PYTHON='/usr/bin/python2.7'):
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
def hermetic_environment_as(**kwargs):
  """Set the environment to the supplied values from an empty state."""
  old_environment, os.environ = os.environ, {}
  try:
    with environment_as(**kwargs):
      yield
  finally:
    os.environ = old_environment


@contextmanager
def _stdio_stream_as(src_fd, dst_fd, dst_sys_attribute, mode):
  """Replace the given dst_fd and attribute on `sys` with an open handle to the given src_fd."""
  if src_fd == -1:
    src = open('/dev/null', mode)
    src_fd = src.fileno()

  # Capture the python and os level file handles.
  old_dst = getattr(sys, dst_sys_attribute)
  old_dst_fd = os.dup(dst_fd)
  if src_fd != dst_fd:
    os.dup2(src_fd, dst_fd)

  # Open up a new file handle to temporarily replace the python-level io object, then yield.
  new_dst = os.fdopen(dst_fd, mode)
  setattr(sys, dst_sys_attribute, new_dst)
  try:
    yield
  finally:
    new_dst.close()

    # Restore the python and os level file handles.
    os.dup2(old_dst_fd, dst_fd)
    setattr(sys, dst_sys_attribute, old_dst)


@contextmanager
def stdio_as(stdout_fd, stderr_fd, stdin_fd):
  """Redirect sys.{stdout, stderr, stdin} to alternate file descriptors.

  As a special case, if a given destination fd is `-1`, we will replace it with an open file handle
  to `/dev/null`.

  NB: If the filehandles for sys.{stdout, stderr, stdin} have previously been closed, it's
  possible that the OS has repurposed fds `0, 1, 2` to represent other files or sockets. It's
  impossible for this method to locate all python objects which refer to those fds, so it's up
  to the caller to guarantee that `0, 1, 2` are safe to replace.
  """
  with _stdio_stream_as(stdin_fd,  0, 'stdin',  'rb'),\
       _stdio_stream_as(stdout_fd, 1, 'stdout', 'wb'),\
       _stdio_stream_as(stderr_fd, 2, 'stderr', 'wb'):
    yield


@contextmanager
def signal_handler_as(sig, handler):
  """Temporarily replaces a signal handler for the given signal and restores the old handler.

  :param int sig: The target signal to replace the handler for (e.g. signal.SIGINT).
  :param func handler: The new temporary handler.
  """
  old_handler = signal.signal(sig, handler)
  try:
    yield
  finally:
    signal.signal(sig, old_handler)


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
  """A with-context for zip files.

  Passes through *args and **kwargs to zipfile.ZipFile.

  :API: public

  :param path_or_file: Full path to zip file.
  :param args: Any extra args accepted by `zipfile.ZipFile`.
  :param kwargs: Any extra keyword args accepted by `zipfile.ZipFile`.
  :raises: `InvalidZipPath` if path_or_file is invalid.
  :raises: `zipfile.BadZipfile` if zipfile.ZipFile cannot open a zip at path_or_file.
  :returns: `class 'contextlib.GeneratorContextManager`.
  """
  if not path_or_file:
    raise InvalidZipPath('Invalid zip location: {}'.format(path_or_file))
  allowZip64 = kwargs.pop('allowZip64', True)
  try:
    zf = zipfile.ZipFile(path_or_file, *args, allowZip64=allowZip64, **kwargs)
  except zipfile.BadZipfile as bze:
    # Use the realpath in order to follow symlinks back to the problem source file.
    raise zipfile.BadZipfile("Bad Zipfile {0}: {1}".format(os.path.realpath(path_or_file), bze))
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
