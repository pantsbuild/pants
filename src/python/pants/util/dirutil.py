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
import uuid
from collections import defaultdict
from contextlib import contextmanager

from pants.util.strutil import ensure_text


def longest_dir_prefix(path, prefixes):
  """Given a list of prefixes, return the one that is the longest prefix to the given path.

  Returns None if there are no matches.
  """
  longest_match, longest_prefix = 0, None
  for prefix in prefixes:
    if fast_relpath_optional(path, prefix) is not None and len(prefix) > longest_match:
      longest_match, longest_prefix = len(prefix), prefix

  return longest_prefix


def fast_relpath(path, start):
  """A prefix-based relpath, with no normalization or support for returning `..`."""
  relpath = fast_relpath_optional(path, start)
  if relpath is None:
    raise ValueError('{} is not a directory containing {}'.format(start, path))
  return relpath


def fast_relpath_optional(path, start):
  """A prefix-based relpath, with no normalization or support for returning `..`.

  Returns None if `start` is not a directory-aware prefix of `path`.
  """
  if len(start) == 0:
    # Empty prefix.
    return path

  # Determine where the matchable prefix ends.
  pref_end = len(start) - 1 if start[-1] == '/' else len(start)
  if pref_end > len(path):
    # The prefix is too long to match.
    return None
  elif path[:pref_end] == start[:pref_end] and (len(path) == pref_end or path[pref_end] == '/'):
    # The prefix matches, and the entries are either identical, or the suffix indicates that
    # the prefix is a directory.
    return path[pref_end+1:]


def safe_mkdir(directory, clean=False):
  """Ensure a directory is present.

  If it's not there, create it.  If it is, no-op. If clean is True, ensure the dir is empty.

  :API: public
  """
  if clean:
    safe_rmtree(directory)
  try:
    os.makedirs(directory)
  except OSError as e:
    if e.errno != errno.EEXIST:
      raise


def safe_mkdir_for(path):
  """Ensure that the parent directory for a file is present.

  If it's not there, create it. If it is, no-op.
  """
  safe_mkdir(os.path.dirname(path), clean=False)


def safe_file_dump(filename, payload):
  """Write a string to a file.

  :param string filename: The filename of the file to write to.
  :param string payload: The string to write to the file.
  """
  with safe_open(filename, 'wb') as f:
    f.write(payload)


def read_file(filename):
  """Read and return the contents of a file in a single file.read().

  :param string filename: The filename of the file to read.
  :returns: The contents of the file.
  :rtype: string
  """
  with open(filename, 'rb') as f:
    return f.read()


def safe_walk(path, **kwargs):
  """Just like os.walk, but ensures that the returned values are unicode objects.

    This isn't strictly safe, in that it is possible that some paths
    will not be decodeable, but that case is rare, and the only
    alternative is to somehow avoid all interaction between paths and
    unicode objects, which seems especially tough in the presence of
    unicode_literals. See e.g.
    https://mail.python.org/pipermail/python-dev/2008-December/083856.html

    :API: public
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

  :API: public
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
  """Delete a directory if it's present. If it's not present, no-op.

  Note that if the directory argument is a symlink, only the symlink will
  be deleted.

  :API: public
  """
  if os.path.islink(directory):
    safe_delete(directory)
  else:
    shutil.rmtree(directory, ignore_errors=True)


def safe_open(filename, *args, **kwargs):
  """Open a file safely, ensuring that its directory exists.

  :API: public
  """
  safe_mkdir_for(filename)
  return open(filename, *args, **kwargs)


def safe_delete(filename):
  """Delete a file safely. If it's not present, no-op."""
  try:
    os.unlink(filename)
  except OSError as e:
    if e.errno != errno.ENOENT:
      raise


def safe_concurrent_rename(src, dst):
  """Rename src to dst, ignoring errors due to dst already existing.

  Useful when concurrent processes may attempt to create dst, and it doesn't matter who wins.
  """
  # Delete dst, in case it existed (with old content) even before any concurrent processes
  # attempted this write. This ensures that at least one process writes the new content.
  if os.path.isdir(src):  # Note that dst may not exist, so we test for the type of src.
    safe_rmtree(dst)
  else:
    safe_delete(dst)
  try:
    shutil.move(src, dst)
  except IOError as e:
    if e.errno != errno.EEXIST:
      raise


def safe_rm_oldest_items_in_dir(root_dir, num_of_items_to_keep, excludes=frozenset()):
  """
  Keep `num_of_items_to_keep` newly modified items besides `excludes` in `root_dir` then remove the rest.
  :param root_dir: the folder to examine
  :param num_of_items_to_keep: number of files/folders/symlinks to keep after the cleanup
  :param excludes: absolute paths excluded from removal (must be prefixed with `root_dir`)
  :return: none
  """
  if os.path.isdir(root_dir):
    found_files = []
    for old_file in os.listdir(root_dir):
      full_path = os.path.join(root_dir, old_file)
      if full_path not in excludes:
        found_files.append((full_path, os.path.getmtime(full_path)))
    found_files = sorted(found_files, key=lambda x: x[1], reverse=True)
    for cur_file, _ in found_files[num_of_items_to_keep:]:
      rm_rf(cur_file)


@contextmanager
def safe_concurrent_creation(target_path):
  """A contextmanager that yields a temporary path and renames it to a final target path when the
  contextmanager exits.

  Useful when concurrent processes may attempt to create a file, and it doesn't matter who wins.

  :param target_path: The final target path to rename the temporary path to.
  :yields: A temporary path containing the original path with a unique (uuid4) suffix.
  """
  safe_mkdir_for(target_path)
  tmp_path = '{}.tmp.{}'.format(target_path, uuid.uuid4().hex)
  try:
    yield tmp_path
  finally:
    if os.path.exists(tmp_path):
      safe_concurrent_rename(tmp_path, target_path)


def chmod_plus_x(path):
  """Equivalent of unix `chmod a+x path`"""
  path_mode = os.stat(path).st_mode
  path_mode &= int('777', 8)
  if path_mode & stat.S_IRUSR:
    path_mode |= stat.S_IXUSR
  if path_mode & stat.S_IRGRP:
    path_mode |= stat.S_IXGRP
  if path_mode & stat.S_IROTH:
    path_mode |= stat.S_IXOTH
  os.chmod(path, path_mode)


def absolute_symlink(source_path, target_path):
  """Create a symlink at target pointing to source using the absolute path.

  :param source_path: Absolute path to source file
  :param target_path: Absolute path to intended symlink
  :raises ValueError if source_path or link_path are not unique, absolute paths
  :raises OSError on failure UNLESS file already exists or no such file/directory
  """
  if not os.path.isabs(source_path):
    raise ValueError("Path for source : {} must be absolute".format(source_path))
  if not os.path.isabs(target_path):
    raise ValueError("Path for link : {} must be absolute".format(target_path))
  if source_path == target_path:
    raise ValueError("Path for link is identical to source : {}".format(source_path))
  try:
    if os.path.lexists(target_path):
      if os.path.islink(target_path) or os.path.isfile(target_path):
        os.unlink(target_path)
      else:
        shutil.rmtree(target_path)
    safe_mkdir_for(target_path)
    os.symlink(source_path, target_path)
  except OSError as e:
    # Another run may beat us to deletion or creation.
    if not (e.errno == errno.EEXIST or e.errno == errno.ENOENT):
      raise


def relative_symlink(source_path, link_path):
  """Create a symlink at link_path pointing to relative source

  :param source_path: Absolute path to source file
  :param link_path: Absolute path to intended symlink
  :raises ValueError if source_path or link_path are not unique, absolute paths
  :raises OSError on failure UNLESS file already exists or no such file/directory
  """
  if not os.path.isabs(source_path):
    raise ValueError("Path for source:{} must be absolute".format(source_path))
  if not os.path.isabs(link_path):
    raise ValueError("Path for link:{} must be absolute".format(link_path))
  if source_path == link_path:
    raise ValueError("Path for link is identical to source:{}".format(source_path))
  # The failure state below had a long life as an uncaught error. No behavior was changed here, it just adds a catch.
  # Raising an exception does differ from absolute_symlink, which takes the liberty of deleting existing directories.
  if os.path.isdir(link_path) and not os.path.islink(link_path):
    raise ValueError("Path for link would overwrite an existing directory: {}".format(link_path))
  try:
    if os.path.lexists(link_path):
      os.unlink(link_path)
    rel_path = os.path.relpath(source_path, os.path.dirname(link_path))
    os.symlink(rel_path, link_path)
  except OSError as e:
    # Another run may beat us to deletion or creation.
    if not (e.errno == errno.EEXIST or e.errno == errno.ENOENT):
      raise


def relativize_path(path, rootdir):
  """

  :API: public
  """
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

    :API: public

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


def get_basedir(path):
  """Returns the base directory of a path.

  Examples:
    get_basedir('foo/bar/baz') --> 'foo'
    get_basedir('/foo/bar/baz') --> ''
    get_basedir('foo') --> 'foo'
  """
  return path[:path.index(os.sep)] if os.sep in path else path


def rm_rf(name):
  """Remove a file or a directory similarly to running `rm -rf <name>` in a UNIX shell.

  :param str name: the name of the file or directory to remove.
  :raises: OSError on error.
  """
  if not os.path.exists(name):
    return

  try:
    # Avoid using safe_rmtree so we can detect failures.
    shutil.rmtree(name)
  except OSError as e:
    if e.errno == errno.ENOTDIR:
      # 'Not a directory', but a file. Attempt to os.unlink the file, raising OSError on failure.
      safe_delete(name)
    elif e.errno != errno.ENOENT:
      # Pass on 'No such file or directory', otherwise re-raise OSError to surface perm issues etc.
      raise
