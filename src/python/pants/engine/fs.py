# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import binary_type, text_type

from pants.base.project_tree import Dir, File
from pants.engine.rules import RootRule
from pants.option.custom_types import GlobExpansionConjunction
from pants.option.global_options import GlobMatchErrorBehavior
from pants.util.objects import Collection, datatype


class FileContent(datatype([('path', text_type), ('content', binary_type)])):
  """The content of a file."""

  def __repr__(self):
    return 'FileContent(path={}, content=(len:{}))'.format(self.path, len(self.content))

  def __str__(self):
    return repr(self)


class Path(datatype([('path', text_type), 'stat'])):
  """A filesystem path, holding both its symbolic path name, and underlying canonical Stat.

  Both values are relative to the ProjectTree's buildroot.
  """


class PathGlobs(datatype([
    'include',
    'exclude',
    ('glob_match_error_behavior', GlobMatchErrorBehavior),
    ('conjunction', GlobExpansionConjunction),
])):
  """A wrapper around sets of filespecs to include and exclude.

  The syntax supported is roughly git's glob syntax.

  NB: this object is interpreted from within Snapshot::lift_path_globs() -- that method will need to
  be aware of any changes to this object's definition.
  """

  def __new__(cls, include, exclude=(), glob_match_error_behavior=None, conjunction=None):
    """Given various file patterns create a PathGlobs object (without using filesystem operations).

    :param include: A list of filespecs to include.
    :param exclude: A list of filespecs to exclude.
    :param glob_match_error_behavior: The value to pass to GlobMatchErrorBehavior.create()
    :rtype: :class:`PathGlobs`
    """
    return super(PathGlobs, cls).__new__(
      cls,
      include=tuple(include),
      exclude=tuple(exclude),
      glob_match_error_behavior=GlobMatchErrorBehavior.create(glob_match_error_behavior),
      conjunction=GlobExpansionConjunction.create(conjunction))


class PathGlobsAndRoot(datatype([('path_globs', PathGlobs), ('root', text_type)])):
  pass


class DirectoryDigest(datatype([('fingerprint', text_type), ('serialized_bytes_length', int)])):
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
      self.fingerprint,
      self.serialized_bytes_length
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
  def is_empty(self):
    return self == EMPTY_SNAPSHOT

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


class MergedDirectories(datatype([('directories', tuple)])):
  pass


class DirectoryToMaterialize(datatype([('path', text_type), ('directory_digest', DirectoryDigest)])):
  """A request to materialize the contents of a directory digest at the provided path."""
  pass

FilesContent = Collection.of(FileContent)


# TODO: don't recreate this in python, get this from fs::EMPTY_DIGEST somehow.
_EMPTY_FINGERPRINT = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'


EMPTY_DIRECTORY_DIGEST = DirectoryDigest(
  fingerprint=text_type(_EMPTY_FINGERPRINT),
  serialized_bytes_length=0
)

EMPTY_SNAPSHOT = Snapshot(
  directory_digest=EMPTY_DIRECTORY_DIGEST,
  path_stats=(),
)


def create_fs_rules():
  """Creates rules that consume the intrinsic filesystem types."""
  return [
    RootRule(DirectoryDigest),
    RootRule(MergedDirectories),
    RootRule(PathGlobs),
  ]
