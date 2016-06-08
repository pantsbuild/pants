# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import fnmatch
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


class Stats(datatype('Stats', ['files', 'dirs', 'links'])):
  """Sets of File, Dir, and Link objects."""

  def __new__(cls, files=tuple(), dirs=tuple(), links=tuple()):
    return super(Stats, cls).__new__(cls, files, dirs, links)


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
  """
  normed = normpath(path)
  if path.endswith(os_sep + '.'):
    return normed + os_sep + '.'
  return normed


class PathGlob(AbstractClass):
  """A filename pattern.

  All PathGlob subclasses represent in-progress recursion that may match zero or more Stats. The
  leaves of a "tree" of PathGlobs will be Path objects which may or may not exist.
  """

  _DOUBLE = '**'
  _SINGLE = '*'

  @classmethod
  def create_from_spec(cls, ftype, canonical_at, filespec):
    """Given a filespec, return a PathGlob object.

    :param ftype: The Stat subclass intended to be matched by this PathGlobs. TODO: this
      value is only used by the Scheduler currently, which is weird. Move to a wrapper?
    :param canonical_at: A path relative to the ProjectTree that is known to be
      canonical. This requirement exists in order to avoid "accidentally"
      traversing symlinks during expansion of a PathGlobs, which would break filesystem
      invalidation. TODO: Consider asserting that this is a `realpath`.
    :param filespec: A filespec, relative to canonical_at.

    TODO: Because `create_from_spec` is called recursively, this method should work harder to
    avoid splitting/joining. Optimization needed.
    """

    parts = _norm_with_dir(filespec).split(os_sep)
    if cls._DOUBLE in parts[0]:
      if parts[0] != cls._DOUBLE:
        raise ValueError(
            'Illegal component "{}" in filespec: {}'.format(parts[0], join(canonical_at, filespec)))
      # There is a double-wildcard in a dirname of the path: double wildcards are recursive,
      # so there are two remainder possibilities: one with the double wildcard included, and the
      # other without.
      remainders = (join(*parts[1:]), join(*parts[0:]))
      return PathDirWildcard(ftype, canonical_at, parts[0], remainders)
    elif cls._SINGLE not in parts[0]:
      # A literal path component. Look up the first non-canonical component.
      if len(parts) == 1:
        return Path(join(canonical_at, parts[0]))
      return PathLiteral(ftype, join(canonical_at, parts[0]), join(*parts[1:]))
    elif len(parts) == 1:
      # This is the path basename, and it contains a wildcard.
      return PathWildcard(canonical_at, parts[0])
    else:
      # This is a path dirname, and it contains a wildcard.
      remainders = (join(*parts[1:]),)
      return PathDirWildcard(ftype,
                             canonical_at,
                             parts[0],
                             remainders)


class Path(datatype('Path', ['path']), PathGlob):
  """A potentially non-existent filesystem path, relative to the ProjectTree's buildroot."""

  def __new__(cls, path):
    return super(Path, cls).__new__(cls, normpath(six.text_type(path)))

  @property
  def dirname(self):
    return dirname(self.path)


class PathWildcard(datatype('PathWildcard', ['directory', 'wildcard']), PathGlob):
  """A PathGlob with a wildcard in the basename component."""


class PathLiteral(datatype('PathLiteral', ['ftype', 'directory', 'remainder']), PathGlob):
  """A PathGlob representing a partially-expanded literal Path.

  While it still requires recursion, a PathLiteral is simpler to execute than either `wildcard`
  type: it only needs to stat each directory on the way down, rather than listing them.
  """


class PathDirWildcard(datatype('PathDirWildcard', ['ftype', 'directory', 'wildcard', 'remainders']), PathGlob):
  """A PathGlob with a single or double-level wildcard in a directory name.

  Each remainders value is applied relative to each directory matched by the wildcard.
  """


class PathGlobs(datatype('PathGlobs', ['ftype', 'dependencies'])):
  """A set of 'PathGlob' objects.

  This class consumes the (somewhat hidden) support in FilesetWithSpec for normalizing
  globs/rglobs/zglobs into 'filespecs'.

  A glob ending in 'os.sep' explicitly matches a directory; otherwise, globs only match
  files.
  """

  @classmethod
  def create(cls, ftype, relative_to, files=None, globs=None, rglobs=None, zglobs=None):
    """Given various file patterns create a PathGlobs object (without using filesystem operations).

    TODO: This currently sortof-executes parsing via 'to_filespec'. Should maybe push that out to
    callers to make them deal with errors earlier.

    :param relative_to: The path that all patterns are relative to (which will itself be relative
                        to the buildroot).
    :param ftype: A Stat subclass indicating which Stat type will be matched.
    :param files: A list of relative file paths to include.
    :type files: list of string.
    :param string globs: A relative glob pattern of files to include.
    :param string rglobs: A relative recursive glob pattern of files to include.
    :param string zglobs: A relative zsh-style glob pattern of files to include.
    :param zglobs: A relative zsh-style glob pattern of files to include.
    :rtype: :class:`PathGlobs`
    """
    relative_to = normpath(relative_to)
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
    return cls.create_from_specs(ftype, relative_to, filespecs)

  @classmethod
  def create_from_specs(cls, ftype, relative_to, filespecs):
    return cls(ftype, tuple(PathGlob.create_from_spec(ftype, relative_to, filespec)
                            for filespec in filespecs))


def scan_directory(project_tree, directory):
  """List Paths directly below the given path, relative to the ProjectTree.

  Fails eagerly if the path does not exist or is not a directory: since the input is
  a `Dir` instance, the path it represents should already have been confirmed to be an
  existing directory.

  :returns: A Stats object containing the members of the directory.
  """
  dirs = list()
  files = list()
  links = list()
  for stat in project_tree.scandir(directory.path):
    if type(stat) is Dir:
      dirs.append(stat)
    elif type(stat) is File:
      files.append(stat)
    elif type(stat) is Link:
      links.append(stat)
    else:
      raise ValueError('Unrecognized stat type for {}: {}'.format(project_tree, stat))
  return Stats(files=tuple(files),
               dirs=tuple(dirs),
               links=tuple(links))


def merge_stats(stats_list):
  """Merge Stats lists."""
  def generate(field):
    for stats in stats_list:
      for stat in getattr(stats, field):
        yield stat
  return Stats(files=tuple(generate('files')),
               dirs=tuple(generate('dirs')),
               links=tuple(generate('links')))


def apply_path_wildcard(stats, path_wildcard):
  """Filter the given Stats object using the given PathWildcard."""
  def filtered(entries):
    return tuple(stat for stat in entries
                 if fnmatch.fnmatch(basename(stat.path), path_wildcard.wildcard))
  return Stats(files=filtered(stats.files), dirs=filtered(stats.dirs), links=filtered(stats.links))


def apply_path_literal(dirs, path_literal):
  """Given a PathLiteral, generate a PathGlobs object with a longer canonical_at prefix."""
  ftype = path_literal.ftype
  if len(dirs.dependencies) > 1:
    raise AssertionError('{} matched more than one directory!: {}'.format(path_literal, dirs))
  return PathGlobs(ftype, tuple(PathGlob.create_from_spec(ftype, d.path, path_literal.remainder)
                                for d in dirs.dependencies))


def apply_path_dir_wildcard(dirs, path_dir_wildcard):
  """Given a PathDirWildcard, compute a PathGlobs object that encompasses its children.

  The resulting PathGlobs will have longer canonical prefixes than this wildcard, in the
  sense that they will be relative to known-canonical subdirectories.
  """
  ftype = path_dir_wildcard.ftype
  paths = [d.path for d in dirs.dependencies
           if fnmatch.fnmatch(basename(d.path), path_dir_wildcard.wildcard)]
  return PathGlobs(ftype, tuple(PathGlob.create_from_spec(ftype, p, remainder)
                                for p in paths
                                for remainder in path_dir_wildcard.remainders))


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

  This is used to allow the Stat for a path to be satisfied by the result of a scandir call.
  """
  def f(field):
    return tuple(s for s in getattr(stats, field) if s.path == path.path)
  return Stats(files=f('files'), dirs=f('dirs'), links=f('links'))


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


def identity(v):
  return v


Dirs = Collection.of(Dir)
Files = Collection.of(File)
FilesContent = Collection.of(FileContent)
FilesDigest = Collection.of(FileDigest)
Links = Collection.of(Link)


def create_fs_tasks():
  """Creates tasks that consume the native filesystem Node type."""
  return [
    # Glob execution.
    (Stats,
     [SelectProjection(Stats, Dir, ('directory',), PathWildcard),
      Select(PathWildcard)],
     apply_path_wildcard),
    (PathGlobs,
     [SelectProjection(Dirs, Path, ('directory',), PathLiteral),
      Select(PathLiteral)],
     apply_path_literal),
    (PathGlobs,
     [SelectProjection(Dirs, Dir, ('directory',), PathDirWildcard),
      Select(PathDirWildcard)],
     apply_path_dir_wildcard),
    (Stats,
     [SelectDependencies(Stats, PathGlobs)],
     merge_stats),
  ] + [
    # Link resolution.
    (Dirs,
     [Select(Stats),
      SelectProjection(Dirs, Links, ('links',), Stats)],
     resolve_dir_links),
    (Dirs,
     [SelectProjection(Dirs, Path, ('path',), ReadLink)],
     identity),
    (Files,
     [Select(Stats),
      SelectProjection(Files, Links, ('links',), Stats)],
     resolve_file_links),
    (Files,
     [SelectProjection(Files, Path, ('path',), ReadLink)],
     identity),
    (Stats,
     [SelectProjection(Stats, Dir, ('dirname',), Path),
      Select(Path)],
     filter_path_stats),
  ] + [
    # TODO: These are boilerplatey: aggregation should become native:
    #   see https://github.com/pantsbuild/pants/issues/3169
    (Files,
     [SelectDependencies(Files, Links)],
     merge_files),
    (Dirs,
     [SelectDependencies(Dirs, Links)],
     merge_dirs),
    (FilesContent,
     [SelectDependencies(FileContent, Files)],
     FilesContent),
    (FilesDigest,
     [SelectDependencies(FileDigest, Files)],
     FilesDigest),
  ]
