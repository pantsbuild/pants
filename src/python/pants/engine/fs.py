# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import fnmatch
from abc import abstractproperty
from hashlib import sha1
from os import sep as os_sep
from os.path import basename, dirname, join, normpath

import six
from twitter.common.collections.orderedset import OrderedSet

from pants.base.project_tree import Dir, File, Link
from pants.engine.selectors import Collection, Select, SelectDependencies, SelectProjection
from pants.source.wrapped_globs import Globs, RGlobs, ZGlobs
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class ReadLink(datatype('ReadLink', ['path'])):
  """The result of reading a symbolic link."""

  def __new__(cls, path):
    return super(ReadLink, cls).__new__(cls, six.text_type(path))


class Stats(datatype('Stats', ['dependencies'])):
  """A set of Stat objects."""

  def _filtered(self, cls):
    return tuple(s for s in self.dependencies if type(s) is cls)

  @property
  def files(self):
    return self._filtered(File)

  @property
  def dirs(self):
    return self._filtered(Dir)

  @property
  def links(self):
    return self._filtered(Link)


class Paths(datatype('Paths', ['paths', 'stats'])):
  """A set of known-existing symbolic paths with their underlying canonical Stats."""

  def __new__(cls, paths, stats):
    if len(paths) != len(stats):
      raise ValueError('{} expects to receive equal-length lists. Got:\n  {}\n  {}'.format(
        cls, paths, stats))
    return super(Paths, cls).__new__(cls, paths, stats)


class FileContent(datatype('FileContent', ['path', 'content'])):
  """The content of a file, or None if it did not exist."""

  def __repr__(self):
    content_str = '(len:{})'.format(len(self.content)) if self.content is not None else 'None'
    return 'FileContent(path={}, content={})'.format(self.path, content_str)

  def __str__(self):
    return repr(self)


class FileDigest(datatype('FileDigest', ['path', 'digest'])):
  """A unique fingerprint for the content of a File."""


def _norm_with_dir(path):
  """Form of `normpath` that preserves a trailing slash-dot.

  In this case, a trailing slash-dot is used to explicitly indicate that a directory is
  being matched.

  TODO: No longer the case, AFAIK: could probably switch to just normpath.
  """
  normed = normpath(path)
  if path.endswith(os_sep + '.'):
    return normed + os_sep + '.'
  return normed


class Path(datatype('Path', ['path'])):
  """A potentially non-existent filesystem path, relative to the ProjectTree's buildroot."""

  def __new__(cls, path):
    return super(Path, cls).__new__(cls, normpath(six.text_type(path)))

  @property
  def dirname(self):
    return dirname(self.path)


class PathGlob(AbstractClass):
  """A filename pattern.

  All PathGlob subclasses represent in-progress recursion that may match zero or more Stats. The
  leaves of a "tree" of PathGlobs will be Path objects which may or may not exist.
  """

  _DOUBLE = '**'
  _SINGLE = '*'

  @abstractproperty
  def canonical_stat(self):
    """A Dir relative to the ProjectTree, to which the remainder of this PathGlob is relative."""

  @abstractproperty
  def symbolic_path(self):
    """The symbolic name (specific to the execution of this PathGlob) for the canonical_stat."""

  @classmethod
  def create_from_spec(cls, canonical_stat, symbolic_path, filespec):
    """Given a filespec, return a PathGlob object.

    :param canonical_stat: A canonical Dir relative to the ProjectTree, to which the filespec
      is relative.
    :param symbolic_path: A symbolic name for the canonical_stat (or the same name, if no symlinks
      were traversed while expanding it).
    :param filespec: A filespec, relative to the canonical_stat.
    """
    if not isinstance(canonical_stat, Dir):
      raise ValueError('Expected a Dir as the canonical_stat. Got: {}'.format(canonical_stat))

    parts = _norm_with_dir(filespec).split(os_sep)
    if cls._DOUBLE in parts[0]:
      if parts[0] != cls._DOUBLE:
        raise ValueError(
            'Illegal component "{}" in filespec under {}: {}'.format(
              parts[0], symbolic_path, filespec))
      # There is a double-wildcard in a dirname of the path: double wildcards are recursive,
      # so there are two remainder possibilities: one with the double wildcard included, and the
      # other without.
      remainders = (join(*parts[1:]), join(*parts[0:]))
      return PathDirWildcard(canonical_stat, symbolic_path, parts[0], remainders)
    elif len(parts) == 1:
      # This is the path basename, and it may contain a single wildcard.
      return PathWildcard(canonical_stat, symbolic_path, parts[0])
    elif cls._SINGLE not in parts[0]:
      return PathLiteral(canonical_stat, symbolic_path, parts[0], join(*parts[1:]))
    else:
      # This is a path dirname, and it contains a wildcard.
      remainders = (join(*parts[1:]),)
      return PathDirWildcard(canonical_stat, symbolic_path, parts[0], remainders)


class PathWildcard(datatype('PathWildcard', ['canonical_stat', 'symbolic_path', 'wildcard']), PathGlob):
  """A PathGlob with a wildcard in the basename component."""


class PathLiteral(datatype('PathLiteral', ['canonical_stat', 'symbolic_path', 'literal', 'remainder']), PathGlob):
  """A PathGlob representing a partially-expanded literal Path.

  While it still requires recursion, a PathLiteral is simpler to execute than either `wildcard`
  type: it only needs to stat each directory on the way down, rather than listing them.

  TODO: Should be possible to merge with PathDirWildcard.
  """

  @property
  def directory(self):
    return join(self.canonical_stat.path, self.literal)


class PathDirWildcard(datatype('PathDirWildcard', ['canonical_stat', 'symbolic_path', 'wildcard', 'remainders']), PathGlob):
  """A PathGlob with a single or double-level wildcard in a directory name.

  Each remainders value is applied relative to each directory matched by the wildcard.
  """


class PathGlobs(datatype('PathGlobs', ['dependencies'])):
  """A set of 'PathGlob' objects.

  This class consumes the (somewhat hidden) support in FilesetWithSpec for normalizing
  globs/rglobs/zglobs into 'filespecs'.

  A glob ending in 'os.sep' explicitly matches a directory; otherwise, globs only match
  files.
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
    # TODO: We bootstrap the `canonical_stat` value here without validating that it
    # represents a canonical path in the ProjectTree. Should add validation that only
    # canonical paths are used with ProjectTree (probably in ProjectTree).
    return cls(tuple(PathGlob.create_from_spec(Dir(relative_to), relative_to, filespec)
                     for filespec in filespecs))


def scan_directory(project_tree, directory):
  """List Stats directly below the given path, relative to the ProjectTree.

  Fails eagerly if the path does not exist or is not a directory: since the input is
  a `Dir` instance, the path it represents should already have been confirmed to be an
  existing directory.

  :returns: A Stats object containing the members of the directory.
  """
  return Stats(tuple(project_tree.scandir(directory.path)))


def merge_paths(paths_list):
  """Merge Paths lists."""
  return Paths(tuple(p for paths in paths_list for p in paths.paths),
               tuple(s for paths in paths_list for s in paths.stats))


def apply_path_wildcard(stats, path_wildcard):
  """Filter the given Stats object using the given PathWildcard."""
  matched_stats = tuple(s for s in stats.dependencies
                        if fnmatch.fnmatch(basename(s.path), path_wildcard.wildcard))
  matched_paths = tuple(normpath(join(path_wildcard.symbolic_path, basename(s.path)))
                        for s in matched_stats)
  return Paths(matched_paths, matched_stats)


def apply_path_literal(dirs, path_literal):
  """Given a PathLiteral, generate a PathGlobs object with a longer canonical_at prefix.

  Expects to match zero or one directory.
  """
  if len(dirs.dependencies) > 1:
    raise AssertionError('{} matched more than one directory!: {}'.format(path_literal, dirs))

  paths = [(d, join(path_literal.symbolic_path, path_literal.literal)) for d in dirs.dependencies]
  # For each match, create a PathGlob.
  path_globs = tuple(PathGlob.create_from_spec(canonical_stat, symbolic_path, path_literal.remainder)
                     for canonical_stat, symbolic_path in paths)
  return PathGlobs(path_globs)


def apply_path_dir_wildcard(dirs, path_dir_wildcard):
  """Given a PathDirWildcard, compute a PathGlobs object that encompasses its children.

  The resulting PathGlobs will have longer canonical prefixes than this wildcard, in the
  sense that they will be relative to known-canonical subdirectories.
  """
  # Zip each matching+canonical Stat with its symbolic path (made by combining the parent
  # directory's symbolic path with the basename of the matched Stat).
  # TODO: ...it's not correct to use the basename of the canonical_stat here: we've already discarded
  # the name it originally had.
  paths = [(canonical_stat, join(path_dir_wildcard.symbolic_path, basename(canonical_stat.path)))
           for canonical_stat in dirs.dependencies
           if fnmatch.fnmatch(basename(canonical_stat.path), path_dir_wildcard.wildcard)]
  # For each match, create a PathGlob per remainder.
  path_globs = tuple(PathGlob.create_from_spec(canonical_stat, symbolic_path, remainder)
                     for canonical_stat, symbolic_path in paths
                     for remainder in path_dir_wildcard.remainders)
  return PathGlobs(path_globs)


def resolve_dir_links(direct_stats, linked_dirs):
  return Dirs(tuple(d for dirs in (direct_stats.dirs, linked_dirs.dependencies) for d in dirs))


def resolve_file_links(direct_stats, linked_files):
  return Files(tuple(f for files in (direct_stats.files, linked_files.dependencies) for f in files))


def merge_dirs(dirs_list):
  return Dirs(tuple(d for dirs in dirs_list for d in dirs.dependencies))


def merge_files(files_list):
  return Files(tuple(f for files in files_list for f in files.dependencies))


def read_link(project_tree, link):
  return ReadLink(project_tree.readlink(link.path))


def filter_path_stats(stats, path):
  """Filter the given Stats object to contain only entries matching the given Path.

  This is used to allow the Stat for a Path to be satisfied by a scandir for its dirname.
  """
  return Stats(tuple(s for s in stats.dependencies if s.path == path.path))


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
  """Passes through the Stats resulting from resolving an underlying Link."""
  return stats


Dirs = Collection.of(Dir)
Files = Collection.of(File)
FilesContent = Collection.of(FileContent)
FilesDigest = Collection.of(FileDigest)
Links = Collection.of(Link)


def create_fs_tasks():
  """Creates tasks that consume the native filesystem Node type."""
  return [
    # Glob execution.
    (Paths,
     [SelectProjection(Stats, Dir, ('canonical_stat',), PathWildcard),
      Select(PathWildcard)],
     apply_path_wildcard),
    (PathGlobs,
     [SelectProjection(Dirs, Path, ('directory',), PathLiteral),
      Select(PathLiteral)],
     apply_path_literal),
    (PathGlobs,
     [SelectProjection(Dirs, Dir, ('canonical_stat',), PathDirWildcard),
      Select(PathDirWildcard)],
     apply_path_dir_wildcard),
    (Paths,
     [SelectDependencies(Paths, PathGlobs)],
     merge_paths),
  ] + [
    # Link resolution.
    (Dirs,
     [Select(Stats),
      SelectProjection(Dirs, Links, ('links',), Stats)],
     resolve_dir_links),
    (Dirs,
     [SelectProjection(Dirs, Path, ('path',), ReadLink)],
     resolve_link),
    (Files,
     [Select(Stats),
      SelectProjection(Files, Links, ('links',), Stats)],
     resolve_file_links),
    (Files,
     [SelectProjection(Files, Path, ('path',), ReadLink)],
     resolve_link),
    (Stats,
     [SelectProjection(Stats, Dir, ('dirname',), Path),
      Select(Path)],
     filter_path_stats),
    (Files,
     [SelectDependencies(Files, Links)],
     merge_files),
    (Dirs,
     [SelectDependencies(Dirs, Links)],
     merge_dirs),
  ] + [
    # File content.
    (FilesContent,
     [SelectDependencies(FileContent, Files)],
     FilesContent),
    (FilesDigest,
     [SelectDependencies(FileDigest, Files)],
     FilesDigest),
  ]
