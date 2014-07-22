# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import closing, contextmanager
import os
import shutil
import tarfile
import tempfile
import time
import uuid
import zipfile

from twitter.common.lang import Compatibility

from pants.util.dirutil import safe_delete


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
def temporary_dir(root_dir=None, cleanup=True):
  """
    A with-context that creates a temporary directory.

    You may specify the following keyword args:
      root_dir [path]: The parent directory to create the temporary directory.
      cleanup [True/False]: Whether or not to clean up the temporary directory.
  """
  path = tempfile.mkdtemp(dir=root_dir)
  try:
    yield path
  finally:
    if cleanup:
      shutil.rmtree(path, ignore_errors=True)


@contextmanager
def temporary_file_path(root_dir=None, cleanup=True):
  """
    A with-context that creates a temporary file and returns its path.

    You may specify the following keyword args:
      root_dir [path]: The parent directory to create the temporary file.
      cleanup [True/False]: Whether or not to clean up the temporary file.
  """
  with temporary_file(root_dir, cleanup) as fd:
    fd.close()
    yield fd.name


@contextmanager
def temporary_file(root_dir=None, cleanup=True):
  """
    A with-context that creates a temporary file and returns a writeable file descriptor to it.

    You may specify the following keyword args:
      root_dir [path]: The parent directory to create the temporary file.
      cleanup [True/False]: Whether or not to clean up the temporary file.
  """
  with tempfile.NamedTemporaryFile(dir=root_dir, delete=False) as fd:
    try:
      yield fd
    finally:
      if cleanup:
        safe_delete(fd.name)


@contextmanager
def safe_file(path, suffix=None, cleanup=True):
  """A with-context that copies a file, and copies the copy back to the original file on success.

  This is useful for doing work on a file but only changing its state on success.

    - suffix: Use this suffix to create the copy. Otherwise use a random string.
    - cleanup: Whether or not to clean up the copy.
  """
  safe_path = path + '.%s' % suffix or uuid.uuid4()
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
  """
  try:
    zf = zipfile.ZipFile(path_or_file, *args, **kwargs)
  except zipfile.BadZipfile as bze:
    raise zipfile.BadZipfile("Bad Zipfile %s: %s" % (path_or_file, bze))
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
  (path, fileobj) = ((path_or_file, None) if isinstance(path_or_file, Compatibility.string)
                     else (None, path_or_file))
  with closing(tarfile.open(path, *args, fileobj=fileobj, **kwargs)) as tar:
    yield tar


class Timer(object):
  """Very basic with-context to time operations

  Example usage:
    >>> from twitter.common.contextutil import Timer
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
