# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
from binascii import hexlify
from os.path import dirname, join

import six

from pants.base.project_tree import Dir, File, Link
from pants.engine.addressable import Collection
from pants.engine.selectors import Select, SelectDependencies
from pants.util.contextutil import open_tar
from pants.util.dirutil import safe_mkdir
from pants.util.objects import datatype


class ReadLink(datatype('ReadLink', ['path'])):
  """The result of reading a symbolic link."""

  def __new__(cls, path):
    return super(ReadLink, cls).__new__(cls, six.binary_type(path))


class Files(datatype('Files', ['dependencies'])):
  """A collection of Path objects with File stats."""

  @property
  def stats(self):
    return tuple(s.stat for s in self.dependencies)


class FileContent(datatype('FileContent', ['path', 'content'])):
  """The content of a file, or None if it did not exist."""

  def __repr__(self):
    content_str = '(len:{})'.format(len(self.content)) if self.content is not None else 'None'
    return 'FileContent(path={}, content={})'.format(self.path, content_str)

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
  def create(relative_to, include, exclude):
    """Given various file patterns create a PathGlobs object (without using filesystem operations).

    :param relative_to: The path that all patterns are relative to (which will itself be relative
      to the buildroot).
    :param included: A list of filespecs to include.
    :param excluded: A list of filespecs to exclude.
    :rtype: :class:`PathGlobs`
    """
    return PathGlobs(tuple(join(relative_to, f) for f in include),
                     tuple(join(relative_to, f) for f in exclude))


class DirectoryListing(datatype('DirectoryListing', ['directory', 'dependencies'])):
  """A list of Stat objects representing a directory listing."""


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
  def files(self):
    return [p for p in self.path_stats if type(p.stat) == File]

  def __repr__(self):
    return '''Snapshot(fingerprint='{}', entries={})'''.format(hexlify(self.fingerprint)[:8], len(self.path_stats))

  def __str__(self):
    return repr(self)


def snapshot_noop(*args):
  raise Exception('This task is replaced intrinsically, and should not run.')


def _snapshot_path(snapshot, archive_root):
  safe_mkdir(archive_root)
  tar_location = join(archive_root, '{}.tar'.format(snapshot.fingerprint))
  return tar_location


def extract_snapshot(snapshot_archive_root, snapshot, sandbox_dir):
  with open_tar(_snapshot_path(snapshot, snapshot_archive_root), errorlevel=1) as tar:
    tar.extractall(sandbox_dir)


class _SnapshotDirectory(datatype('_SnapshotDirectory', ['root'])):
  """Private singleton value for the snapshot directory."""


def select_snapshot_directory():
  return Select(_SnapshotDirectory)


def scan_directory(project_tree, directory):
  """List Stat objects directly below the given path, relative to the ProjectTree.

  :returns: A DirectoryListing.
  """
  return DirectoryListing(directory, tuple(project_tree.scandir(directory.path)))


def read_link(project_tree, link):
  return ReadLink(project_tree.readlink(link.path))


def file_content(project_tree, f):
  """Return a FileContent for a known-existing File.

  NB: This method fails eagerly, because it expects to be executed only after a caller has
  stat'd a path to determine that it is, in fact, an existing File.
  """
  return FileContent(f.path, project_tree.content(f.path))


def resolve_link(stats):
  """Passes through the projected Files/Dirs for link resolution."""
  return stats


def files_content(files, file_values):
  entries = tuple(FileContent(f.path, f_value.content)
                  for f, f_value in zip(files.dependencies, file_values))
  return FilesContent(entries)


FilesContent = Collection.of(FileContent)


def generate_fs_subjects(filenames):
  """Given filenames, generate a set of subjects for invalidation predicate matching."""
  for f in filenames:
    # ReadLink, FileContent, or DirectoryListing for the literal path.
    yield File(f)
    yield Link(f)
    yield Dir(f)
    # Additionally, since the FS event service does not send invalidation events
    # for the root directory, treat any changed file in the root as an invalidation
    # of the root's listing.
    if dirname(f) in ('.', ''):
      yield Dir('')


def create_fs_intrinsics(project_tree):
  def ptree(func):
    p = functools.partial(func, project_tree)
    p.__name__ = '{}_intrinsic'.format(func.__name__)
    return p
  return [
    (DirectoryListing, Dir, ptree(scan_directory)),
    (FileContent, File, ptree(file_content)),
    (ReadLink, Link, ptree(read_link)),
  ]


def create_fs_tasks(project_tree):
  """Creates tasks that consume the intrinsic filesystem types."""
  def ptree(func):
    p = functools.partial(func, project_tree)
    p.__name__ = '{}_intrinsic'.format(func.__name__)
    return p
  return [
    # File content.
    # TODO: Consume a Snapshot in memory.
    (FilesContent,
     [Select(Files),
      SelectDependencies(FileContent, Files, field='stats', field_types=(File,))],
     files_content),
  ] + [
    # Snapshot creation.
    (Snapshot, [], snapshot_noop),
  ]
