# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import atexit
from collections import defaultdict
import errno
import os
import shutil
import stat
import tempfile
import threading


def safe_mkdir(directory, clean=False):
  """Ensure a directory is present.

  If it's not there, create it.  If it is, no-op. If clean is True, ensure the dir is empty."""
  if clean:
    safe_rmtree(directory)
  try:
    os.makedirs(directory)
  except OSError as e:
    if e.errno != errno.EEXIST:
      raise


def safe_mkdir_for(path, clean=False):
  """
    Ensure that the parent directory for a file is present.  If it's not there, create it.
    If it is, no-op. If clean is True, ensure the directory is empty.
  """
  safe_mkdir(os.path.dirname(path), clean)


_MKDTEMP_CLEANER = None
_MKDTEMP_DIRS = defaultdict(set)
_MKDTEMP_LOCK = threading.RLock()


def _mkdtemp_atexit_cleaner():
  for td in _MKDTEMP_DIRS.pop(os.getpid(), []):
    safe_rmtree(td)


def _mkdtemp_unregister_cleaner():
  global _MKDTEMP_CLEANER
  _MKDTEMP_CLEANER = None


def _mkdtemp_register_cleaner(cleaner):
  global _MKDTEMP_CLEANER
  if not cleaner:
    return
  assert callable(cleaner)
  if _MKDTEMP_CLEANER is None:
    atexit.register(cleaner)
    _MKDTEMP_CLEANER = cleaner


def safe_mkdtemp(cleaner=_mkdtemp_atexit_cleaner, **kw):
  """Create a temporary directory that is cleaned up on process exit.

  Arguments are as to tempfile.mkdtemp.
  """
  # Proper lock sanitation on fork [issue 6721] would be desirable here.
  with _MKDTEMP_LOCK:
    return register_rmtree(tempfile.mkdtemp(**kw), cleaner=cleaner)


def register_rmtree(directory, cleaner=_mkdtemp_atexit_cleaner):
  """Register an existing directory to be cleaned up at process exit."""
  with _MKDTEMP_LOCK:
    _mkdtemp_register_cleaner(cleaner)
    _MKDTEMP_DIRS[os.getpid()].add(directory)
  return directory


def safe_rmtree(directory):
  """
    Delete a directory if it's present. If it's not present, no-op.
  """
  if os.path.exists(directory):
    shutil.rmtree(directory, True)


def safe_open(filename, *args, **kwargs):
  """
    Open a file safely (ensuring that the directory components leading up to it
    have been created first.)
  """
  safe_mkdir(os.path.dirname(filename))
  return open(filename, *args, **kwargs)


def safe_delete(filename):
  """
    Delete a file safely. If it's not present, no-op.
  """
  try:
    os.unlink(filename)
  except OSError as e:
    if e.errno != errno.ENOENT:
      raise


def chmod_plus_x(path):
  """
    Equivalent of unix `chmod a+x path`
  """
  path_mode = os.stat(path).st_mode
  path_mode &= int('777', 8)
  if path_mode & stat.S_IRUSR:
    path_mode |= stat.S_IXUSR
  if path_mode & stat.S_IRGRP:
    path_mode |= stat.S_IXGRP
  if path_mode & stat.S_IROTH:
    path_mode |= stat.S_IXOTH
  os.chmod(path, path_mode)


def touch(path, times=None):
  """Equivalent of unix `touch path`.

    :path: The file to touch.
    :times Either a tuple of (atime, mtime) or else a single time to use for both.  If not
           specified both atime and mtime are updated to the current time.
  """
  if times:
    if len(times) > 2:
      raise ValueError('times must either be a tuple of (atime, mtime) or else a single time value '
                       'to use for both.')

    if len(times) == 1:
      times = (times, times)

  with safe_open(path, 'a'):
    os.utime(path, times)
