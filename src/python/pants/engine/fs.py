# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from binascii import hexlify
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


class Snapshot(datatype(['fingerprint', 'digest_length', 'path_stats'])):
  """A Snapshot is a collection of Files and Dirs fingerprinted by their names/content.

  Snapshots are used to make it easier to isolate process execution by fixing the contents
  of the files being operated on and easing their movement to and from isolated execution
  sandboxes.
  """

  def __new__(cls, fingerprint, digest_length, path_stats):
    # We get a unicode instance when this is instantiated, so ensure it is
    # converted to a str.
    return super(Snapshot, cls).__new__(cls, str(fingerprint), digest_length, path_stats)

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
    return '''Snapshot(fingerprint='{}', digest_length='{}', entries={})'''.format(hexlify(self.fingerprint)[:8], self.digest_length, len(self.path_stats))

  def __str__(self):
    return repr(self)


FilesContent = Collection.of(FileContent)


# TODO(cosmicexplorer): don't recreate this in python, get this from
# fs::EMPTY_DIGEST somehow.
_EMPTY_FINGERPRINT = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'


EMPTY_SNAPSHOT = Snapshot(
  fingerprint=_EMPTY_FINGERPRINT,
  digest_length=0,
  path_stats=[],
)


def create_fs_rules():
  """Creates rules that consume the intrinsic filesystem types."""
  return [
    RootRule(PathGlobs),
  ]
