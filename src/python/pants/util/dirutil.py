# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import atexit
import errno
import os
import shutil
import stat
import tempfile
import threading
from collections import defaultdict

from pants.util.strutil import ensure_text


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


def safe_walk(path, **kwargs):
  """Just like os.walk, but ensures that the returned values are unicode objects.

    This isn't strictly safe, in that it is possible that some paths
    will not be decodeable, but that case is rare, and the only
    alternative is to somehow avoid all interaction between paths and
    unicode objects, which seems especially tough in the presence of
    unicode_literals. See e.g.
    https://mail.python.org/pipermail/python-dev/2008-December/083856.html

  """
  # If os.walk is given a text argument, it yields text values; if it
  # is given a binary argument, it yields binary values.
  return os.walk(ensure_text(path), **kwargs)


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


def relativize_path(path, rootdir):
  # Note that we can't test for length and return the shorter of the two, because we need these
  # paths to be stable across systems (e.g., because they get embedded in analysis files),
  # and this choice might be inconsistent across systems. So we assume the relpath is always
  # shorter. We relativize because of a known case of very long full path prefixes on Mesos,
  # so this seems like the right heuristic.
  # Note also that we mustn't call realpath on the path - we need to preserve the symlink structure.
  return os.path.relpath(path, rootdir)


# When running pants under mesos/aurora, the sandbox pathname can be very long. Since it gets
# prepended to most components in the classpath (some from ivy, the rest from the build),
# in some runs the classpath gets too big and exceeds ARG_MAX.
# We prevent this by using paths relative to the current working directory.
def relativize_paths(paths, rootdir):
  return [relativize_path(path, rootdir) for path in paths]


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
