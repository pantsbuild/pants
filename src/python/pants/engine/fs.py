# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from os.path import join

from pants.base.project_tree import Dir, File
from pants.engine.rules import RootRule
from pants.util.objects import Collection, datatype


class FileContent(datatype(['path', 'content'])):
  """The content of a file."""

  def __repr__(self):
    return 'FileContent(path={}, content=(len:{}))'.format(self.path, len(self.content))

  def __str__(self):
    return repr(self)


class Path(datatype(['path', 'stat'])):
  """A filesystem path, holding both its symbolic path name, and underlying canonical Stat.

  Both values are relative to the ProjectTree's buildroot.
  """


class PathGlobs(datatype(['include', 'exclude'])):
  """A wrapper around sets of filespecs to include and exclude.

  The syntax supported is roughly git's glob syntax.
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


class DirectoryDigest(datatype([('fingerprint', str), ('serialized_bytes_length', int)])):
  """A DirectoryDigest is an opaque handle to a set of files known about by the engine.

  The contents of files can be inspected by requesting a FilesContent for it.

  In the future, it will be possible to inspect the file metadata by requesting a Snapshot for it,
  but at the moment we can't install rules which go both:
   PathGlobs -> DirectoryDigest -> Snapshot
   PathGlobs -> Snapshot
  because it would lead to an ambiguity in the engine, and we have existing code which already
  relies on the latter existing. This can be resolved when ordering is removed from Snapshots. See
  https://github.com/pantsbuild/pants/issues/5802
  """

  def __repr__(self):
    return '''DirectoryDigest(fingerprint={}, serialized_bytes_length={})'''.format(
      self.fingerprint[:8],
      self.digest_length
    )

  def __str__(self):
    return repr(self)


class Snapshot(datatype([('directory_digest', DirectoryDigest), ('path_stats', tuple)])):
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


FilesContent = Collection.of(FileContent)


# TODO(cosmicexplorer): don't recreate this in python, get this from
# fs::EMPTY_DIGEST somehow.
_EMPTY_FINGERPRINT = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'


EMPTY_SNAPSHOT = Snapshot(
  directory_digest=DirectoryDigest(
    fingerprint=str(_EMPTY_FINGERPRINT),
    serialized_bytes_length=0
  ),
  path_stats=(),
)


def create_fs_rules():
  """Creates rules that consume the intrinsic filesystem types."""
  return [
    RootRule(PathGlobs),
  ]
