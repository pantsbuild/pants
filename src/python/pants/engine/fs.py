# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import functools
import shutil
from abc import abstractproperty
from fnmatch import fnmatch
from hashlib import sha1
from itertools import chain
from os import sep as os_sep
from os.path import basename, dirname, join, normpath

import six
from twitter.common.collections.orderedset import OrderedSet

from pants.base.project_tree import Dir, File, Link
from pants.engine.addressable import Collection
from pants.engine.selectors import Select, SelectDependencies, SelectProjection
from pants.source.wrapped_globs import Globs, RGlobs, ZGlobs
from pants.util.contextutil import open_tar, temporary_file_path
from pants.util.dirutil import safe_mkdir
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class ReadLink(datatype('ReadLink', ['symbolic_path'])):
  """The result of reading a symbolic link."""

  def __new__(cls, path):
    return super(ReadLink, cls).__new__(cls, six.text_type(path))


class Dirs(datatype('Dirs', ['dependencies'])):
  """A collection of Path objects with Dir stats."""

  @property
  def stats(self):
    return tuple(s.stat for s in self.dependencies)


class Files(datatype('Files', ['dependencies'])):
  """A collection of Path objects with File stats."""

  @property
  def stats(self):
    return tuple(s.stat for s in self.dependencies)


class Links(datatype('Links', ['dependencies'])):
  """A collection of Path objects with Link stats."""


class FilteredPaths(datatype('FilteredPaths', ['paths'])):
  """A wrapper around a Paths object that has been filtered by some pattern."""


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


class Paths(datatype('Paths', ['dependencies'])):
  """A set of Path objects."""

  def _filtered(self, cls):
    return tuple(p for p in self.dependencies if type(p.stat) is cls)

  @property
  def files(self):
    return self._filtered(File)

  @property
  def dirs(self):
    return self._filtered(Dir)

  @property
  def links(self):
    return self._filtered(Link)

  @property
  def link_stats(self):
    return tuple(p.stat for p in self.links)


class PathGlobs(datatype('PathGlobs', ['dependencies'])):
  """A helper class (TODO: possibly unnecessary?) for converting various.

  This class consumes the (somewhat hidden) support in FilesetWithSpec for normalizing
  globs/rglobs/zglobs into 'filespecs' strings.
  """

  @staticmethod
  def create(cls, relative_to, files=None, globs=None, rglobs=None, zglobs=None):
    """Given various file patterns create a PathGlobs object (without using filesystem operations).

    :param relative_to: The path that all patterns are relative to (which will itself be relative
      to the buildroot).
    :param files: A list of relative file paths to include.
    :type files: list of string.
    :param string globs: A relative glob pattern of files to include.
    :param string rglobs: A relative recursive glob pattern of files to include.
    :param string zglobs: A relative zsh-style glob pattern of files to include.
    :param zglobs: A relative zsh-style glob pattern of files to include.
    :rtype: :class:`PathGlobs`
    """
    filespecs = OrderedSet()
    for specs, pattern_cls in ((files, Globs),
                               (globs, Globs),
                               (rglobs, RGlobs),
                               (zglobs, ZGlobs)):
      if not specs:
        continue
      res = pattern_cls.to_filespec(specs)
      exclude = res.get('exclude')
      if exclude:
        raise ValueError('Excludes not supported for PathGlobs. Got: {}'.format(exclude))
      new_specs = res.get('globs', None)
      if new_specs:
        filespecs.update(new_specs)
    return PathGlobs(tuple(join(relative_to, f) for f in filespecs))


class DirectoryListing(datatype('DirectoryListing', ['directory', 'dependencies', 'exists'])):
  """A list of Stat objects representing a directory listing.

  If exists=False, then the entries list will be empty.
  """


class Snapshot(datatype('Snapshot', ['fingerprint', 'files', 'dirs'])):
  """A Snapshot is a collection of Files and Dirs fingerprinted by their names/content.

  Snapshots are used to make it easier to isolate process execution by fixing the contents
  of the files being operated on and easing their movement to and from isolated execution
  sandboxes.
  """

  @property
  def dependencies(self):
    return self.files + self.dirs


def snapshot_noop(*args):
  raise Exception('This task is replaced intrinsically, and should not run.')


def _fingerprint_files_in_tar(file_list, tar_location):
  """
  TODO: This could potentially be implemented by nuking any timestamp entries in
  the tar file, and then fingerprinting the entire thing.

  Also, it's currently ignoring directories, which hashing the entire tar would resolve.
  """
  hasher = sha1()
  with open_tar(tar_location, mode='r', errorlevel=1) as tar:
    for file in file_list.dependencies:
      hasher.update(file.path)
      hasher.update(tar.extractfile(file.path).read())
  return hasher.hexdigest()


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
  try:
    return DirectoryListing(directory, tuple(project_tree.scandir(directory.path)), exists=True)
  except (IOError, OSError) as e:
    if e.errno == errno.ENOENT:
      return DirectoryListing(directory, tuple(), exists=False)
    else:
      raise e


def finalize_path_expansion(paths_expansion_list):
  """Finalize and merge PathExpansion lists into Paths."""
  path_seen = set()
  merged_paths = []
  for paths_expansion in paths_expansion_list:
    for p in paths_expansion.paths.dependencies:
      if p not in path_seen:
        merged_paths.append(p)
        path_seen.add(p)
  return Paths(tuple(merged_paths))


def _zip_links(links, linked_paths):
  """Given a set of Paths and a resolved collection per Link in the Paths, merge."""
  # Alias the resolved destinations with the symbolic name of the Paths used to resolve them.
  if len(links) != len(linked_paths):
    raise ValueError('Expected to receive resolved Paths per Link. Got: {} and {}'.format(
      links, linked_paths))
  return tuple(Path(link.path, dest.dependencies[0].stat)
               for link, dest in zip(links, linked_paths)
               if len(dest.dependencies) > 0)


def resolve_dir_links(direct_paths, linked_dirs):
  return Dirs(direct_paths.dirs + _zip_links(direct_paths.links, linked_dirs))


def resolve_file_links(direct_paths, linked_files):
  return Files(direct_paths.files + _zip_links(direct_paths.links, linked_files))


def read_link(project_tree, link):
  return ReadLink(project_tree.readlink(link.path))


def filter_paths(stats, path_dir_wildcard):
  """Filter the given DirectoryListing object into Paths matching the given PathDirWildcard."""
  entries = [(s, basename(s.path)) for s in stats.dependencies]
  paths = tuple(Path(join(path_dir_wildcard.symbolic_path, basename), stat)
                for stat, basename in entries
                if fnmatch(basename, path_dir_wildcard.wildcard))
  return FilteredPaths(Paths(paths))


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
    # Public
    (FilesContent,
     [Select(Files),
      SelectDependencies(FileContent, Files, field='stats', field_types=(File,))],
     files_content),
  ] + [
    # Snapshot creation.
    (Snapshot, [], snapshot_noop),
  ]
