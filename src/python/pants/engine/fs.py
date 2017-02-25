# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
from binascii import hexlify
from os.path import join

from pants.base.project_tree import Dir, File
from pants.engine.addressable import Collection
from pants.engine.selectors import Select
from pants.util.objects import datatype


class FileContent(datatype('FileContent', ['path', 'content'])):
  """The content of a file."""

  def __repr__(self):
    return 'FileContent(path={}, content=(len:{}))'.format(self.path, len(self.content))

  def __str__(self):
    return repr(self)


class Path(datatype('Path', ['path', 'stat'])):
  """A filesystem path, holding both its symbolic path name, and underlying canonical Stat.

  Both values are relative to the ProjectTree's buildroot.
  """


class PathGlobs(datatype('PathGlobs', ['include', 'exclude'])):
  """A helper class (TODO: possibly unnecessary?) for converting various.

  This class consumes the (somewhat hidden) support in FilesetWithSpec for normalizing
  globs/rglobs/zglobs into 'filespecs' strings.
  """

  @staticmethod
  def create(relative_to, include, exclude=tuple()):
    """Given various file patterns create a PathGlobs object (without using filesystem operations).

    :param relative_to: The path that all patterns are relative to (which will itself be relative
      to the buildroot).
    :param included: A list of filespecs to include.
    :param excluded: A list of filespecs to exclude.
    :rtype: :class:`PathGlobs`
    """
    return PathGlobs(tuple(join(relative_to, f) for f in include),
                     tuple(join(relative_to, f) for f in exclude))


class Snapshot(datatype('Snapshot', ['fingerprint', 'path_stats'])):
  """A Snapshot is a collection of Files and Dirs fingerprinted by their names/content.

  Snapshots are used to make it easier to isolate process execution by fixing the contents
  of the files being operated on and easing their movement to and from isolated execution
  sandboxes.
  """

  @property
  def dirs(self):
    return [p for p in self.path_stats if type(p.stat) == Dir]

  @property
  def dir_stats(self):
    return [p.stat for p in self.dirs]

  @property
  def files(self):
    return [p for p in self.path_stats if type(p.stat) == File]

  @property
  def file_stats(self):
    return [p.stat for p in self.files]

  def __repr__(self):
    return '''Snapshot(fingerprint='{}', entries={})'''.format(hexlify(self.fingerprint)[:8], len(self.path_stats))

  def __str__(self):
    return repr(self)


def snapshot_noop(*args):
  raise Exception('This task is replaced intrinsically, and should never run.')


def files_content_noop(*args):
  raise Exception('This task is replaced intrinsically, and should never run.')


FilesContent = Collection.of(FileContent)


def create_fs_tasks(project_tree):
  """Creates tasks that consume the intrinsic filesystem types."""
  def ptree(func):
    p = functools.partial(func, project_tree)
    p.__name__ = '{}_intrinsic'.format(func.__name__)
    return p
  return [
    # File content.
    (FilesContent, [Select(Snapshot)], files_content_noop),
  ] + [
    # Snapshot creation.
    (Snapshot, [Select(PathGlobs)], snapshot_noop),
  ]
