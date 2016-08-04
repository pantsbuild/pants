# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
from abc import abstractproperty
from fnmatch import fnmatch
from hashlib import sha1
from itertools import chain
from os import sep as os_sep
from os.path import basename, join, normpath

import six
from twitter.common.collections.orderedset import OrderedSet

from pants.base.project_tree import Dir, File, Link
from pants.engine.selectors import Collection, Select, SelectDependencies, SelectProjection
from pants.source.wrapped_globs import Globs, RGlobs, ZGlobs
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class ReadLink(datatype('ReadLink', ['symbolic_path'])):
  """The result of reading a symbolic link."""

  def __new__(cls, path):
    return super(ReadLink, cls).__new__(cls, six.text_type(path))

  @property
  def path_globs(self):
    """Supports projecting the Path resulting from a ReadLink as a PathGlob.

    Because symlinks may be dead or point inside of other symlinks, it's necessary to resolve
    their components from the top of the buildroot.
    """
    return PathGlobs.create_from_specs('', [self.symbolic_path])


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


class FileDigest(datatype('FileDigest', ['path', 'digest'])):
  """A unique fingerprint for the content of a File."""


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


class PathGlob(AbstractClass):
  """A filename pattern.

  All PathGlob subclasses represent in-progress recursion that may match zero or more Paths. The
  leaves of a "tree" of PathGlobs will be Path objects which may or may not exist.
  """

  _DOUBLE = '**'

  @abstractproperty
  def canonical_stat(self):
    """A Dir relative to the ProjectTree, to which the remainder of this PathGlob is relative."""

  @abstractproperty
  def symbolic_path(self):
    """The symbolic name (specific to the execution of this PathGlob) for the canonical_stat."""

  @classmethod
  def _prune_doublestar(cls, parts):
    # This is called only when parts[0] == '**'.
    # Eliminating consecutive '**'s can prevent engine from doing repetitive traversing.
    idx = 1
    while idx < len(parts) and cls._DOUBLE == parts[idx]:
      idx += 1
    return parts[0:1] + parts[idx:]

  @classmethod
  def create_from_spec(cls, canonical_stat, symbolic_path, filespec):
    """Given a filespec, return a tuple of PathGlob objects.

    :param canonical_stat: A canonical Dir relative to the ProjectTree, to which the filespec
      is relative.
    :param symbolic_path: A symbolic name for the canonical_stat (or the same name, if no symlinks
      were traversed while expanding it).
    :param filespec: A filespec, relative to the canonical_stat.
    """
    if not isinstance(canonical_stat, Dir):
      raise ValueError('Expected a Dir as the canonical_stat. Got: {}'.format(canonical_stat))

    parts = normpath(filespec).split(os_sep)
    if canonical_stat == Dir('') and len(parts) == 1 and parts[0] == '.':
      # A request for the root path.
      return (PathRoot(),)
    elif cls._DOUBLE == parts[0]:
      parts = cls._prune_doublestar(parts)

      if len(parts) == 1:
        # Per https://git-scm.com/docs/gitignore:
        #
        #  "A trailing '/**' matches everything inside. For example, 'abc/**' matches all files inside
        #   directory "abc", relative to the location of the .gitignore file, with infinite depth."
        #
        return (PathDirWildcard(canonical_stat, symbolic_path, '*', '**'),
                PathWildcard(canonical_stat, symbolic_path, '*'))

      # There is a double-wildcard in a dirname of the path: double wildcards are recursive,
      # so there are two remainder possibilities: one with the double wildcard included, and the
      # other without.
      pathglob_with_doublestar = PathDirWildcard(canonical_stat, symbolic_path, '*', join(*parts[0:]))
      if len(parts) == 2:
        pathglob_no_doublestar = PathWildcard(canonical_stat, symbolic_path, parts[1])
      else:
        pathglob_no_doublestar = PathDirWildcard(canonical_stat, symbolic_path, parts[1], join(*parts[2:]))
      return (pathglob_with_doublestar, pathglob_no_doublestar)
    elif len(parts) == 1:
      # This is the path basename.
      return (PathWildcard(canonical_stat, symbolic_path, parts[0]),)
    else:
      # This is a path dirname.
      return (PathDirWildcard(canonical_stat, symbolic_path, parts[0], join(*parts[1:])),)


class PathRoot(datatype('PathRoot', []), PathGlob):
  """A PathGlob matching the root of the ProjectTree.

  The root is special because it's the only symbolic path that we can implicit trust is
  not a symlink.
  """
  canonical_stat = Dir('')
  symbolic_path = ''

  paths = Paths((Path(symbolic_path, canonical_stat),))


class PathWildcard(datatype('PathWildcard', ['canonical_stat', 'symbolic_path', 'wildcard']), PathGlob):
  """A PathGlob matching a basename."""


class PathDirWildcard(datatype('PathDirWildcard', ['canonical_stat', 'symbolic_path', 'wildcard', 'remainder']), PathGlob):
  """A PathGlob matching a dirname.

  Remainder value is applied relative to each directory matched by the wildcard.
  """


class PathGlobs(datatype('PathGlobs', ['dependencies'])):
  """A set of 'PathGlob' objects.

  This class consumes the (somewhat hidden) support in FilesetWithSpec for normalizing
  globs/rglobs/zglobs into 'filespecs'.
  """

  @classmethod
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
      excludes = res.get('excludes')
      if excludes:
        raise ValueError('Excludes not supported for PathGlobs. Got: {}'.format(excludes))
      new_specs = res.get('globs', None)
      if new_specs:
        filespecs.update(new_specs)
    return cls.create_from_specs(relative_to, filespecs)

  @classmethod
  def create_from_specs(cls, relative_to, filespecs):
    path_globs = (PathGlob.create_from_spec(Dir(relative_to), relative_to, filespec) for filespec in filespecs)
    return cls(tuple(chain.from_iterable(path_globs)))


class DirectoryListing(datatype('DirectoryListing', ['directory', 'dependencies', 'exists'])):
  """A list of Stat objects representing a directory listing.

  If exists=False, then the entries list will be empty.
  """


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


def merge_paths(paths_list):
  """Merge Paths lists."""
  path_seen = set()
  merged_paths = []
  for paths in paths_list:
    for p in paths.dependencies:
      if p not in path_seen:
        merged_paths.append(p)
        path_seen.add(p)
  return Paths(tuple(merged_paths))


def apply_path_root(path_root):
  """Returns the `Paths` for the root of the repo."""
  return path_root.paths


def apply_path_wildcard(stats, path_wildcard):
  """Filter the given DirectoryListing object using the given PathWildcard."""
  return Paths(tuple(Path(normpath(join(path_wildcard.symbolic_path, basename(s.path))), s)
                     for s in stats.dependencies
                     if fnmatch(basename(s.path), path_wildcard.wildcard)))


def apply_path_dir_wildcard(dirs, path_dir_wildcard):
  """Given a PathDirWildcard, compute a PathGlobs object that encompasses its children.

  The resulting PathGlobs will have longer canonical prefixes than this wildcard, in the
  sense that they will be relative to known-canonical subdirectories.
  """
  # For each matching Path, create a PathGlob per remainder.
  path_globs = (PathGlob.create_from_spec(d.stat, d.path, path_dir_wildcard.remainder) for d in dirs.dependencies)
  return PathGlobs(tuple(chain.from_iterable(path_globs)))


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


def file_digest(project_tree, f):
  """Return a FileDigest for a known-existing File.

  See NB on file_content.
  """
  return FileDigest(f.path, sha1(project_tree.content(f.path)).digest())


def resolve_link(stats):
  """Passes through the projected Files/Dirs for link resolution."""
  return stats


def files_content(files, file_values):
  entries = tuple(FileContent(f.path, f_value.content)
                  for f, f_value in zip(files.dependencies, file_values))
  return FilesContent(entries)


def files_digest(files, file_values):
  entries = tuple(FileDigest(f.path, f_value.digest)
                  for f, f_value in zip(files.dependencies, file_values))
  return FilesDigest(entries)


FilesContent = Collection.of(FileContent)
FilesDigest = Collection.of(FileDigest)


def create_fs_tasks():
  """Creates tasks that consume the native filesystem Node type."""
  return [
    # Glob execution.
    (Paths,
     [SelectDependencies(Paths, PathGlobs)],
     merge_paths),
    (Paths,
     [Select(PathRoot)],
     apply_path_root),
    (Paths,
     [SelectProjection(DirectoryListing, Dir, ('canonical_stat',), PathWildcard),
      Select(PathWildcard)],
     apply_path_wildcard),
    (PathGlobs,
     [SelectProjection(Dirs, Paths, ('paths',), FilteredPaths),
      Select(PathDirWildcard)],
     apply_path_dir_wildcard),
    (FilteredPaths,
     [SelectProjection(DirectoryListing, Dir, ('canonical_stat',), PathDirWildcard),
      Select(PathDirWildcard)],
     filter_paths),
  ] + [
    # Link resolution.
    (Dirs,
     [Select(Paths),
      SelectDependencies(Dirs, Paths, field='link_stats')],
     resolve_dir_links),
    (Files,
     [Select(Paths),
      SelectDependencies(Files, Paths, field='link_stats')],
     resolve_file_links),
    (Dirs,
     [SelectProjection(Dirs, PathGlobs, ('path_globs',), ReadLink)],
     resolve_link),
    (Files,
     [SelectProjection(Files, PathGlobs, ('path_globs',), ReadLink)],
     resolve_link),
  ] + [
    # File content.
    (FilesContent,
     [Select(Files),
      SelectDependencies(FileContent, Files, field='stats')],
     files_content),
    (FilesDigest,
     [Select(Files),
      SelectDependencies(FileDigest, Files, field='stats')],
     files_digest),
  ]
