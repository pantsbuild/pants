# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import fnmatch
from abc import abstractproperty
from os import sep as os_sep
from os.path import basename, join, normpath

import six
from twitter.common.collections.orderedset import OrderedSet

from pants.base.project_tree import PTSTAT_DIR, PTSTAT_FILE, PTSTAT_LINK
from pants.engine.selectors import Collection, Select, SelectDependencies, SelectProjection
from pants.source.wrapped_globs import Globs, RGlobs, ZGlobs
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class Stat(AbstractClass):
  """An existing filesystem path with a known type, relative to the ProjectTree's buildroot.

  Note that in order to preserve these invariants, end-user functions should never directly
  instantiate Stat instances.
  """

  @abstractproperty
  def path(self):
    """:returns: The string path for this Stat."""


class File(datatype('File', ['path']), Stat):
  """A file."""

  def __new__(cls, path):
    return super(File, cls).__new__(cls, six.text_type(path))


class Dir(datatype('Dir', ['path']), Stat):
  """A directory."""

  def __new__(cls, path):
    return super(Dir, cls).__new__(cls, six.text_type(path))


class Link(datatype('Link', ['path']), Stat):
  """A symbolic link."""

  def __new__(cls, path):
    return super(Link, cls).__new__(cls, six.text_type(path))


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


class DirectoryListing(datatype('DirectoryListing', ['directory', 'exists', 'paths'])):
  """A list of entry names representing a directory listing.

  If exists=False, then the entries list will be empty.
  """


def list_directory(project_tree, directory):
  """List Paths directly below the given path, relative to the ProjectTree.

  Raises an exception if the path is not a directory.

  :returns: A DirectoryListing.
  """
  try:
    path = normpath(directory.path)
    entries = [join(path, e) for e in project_tree.listdir(path)]
    return DirectoryListing(directory,
                            True,
                            tuple(Path(e) for e in entries))
  except (IOError, OSError) as e:
    if e.errno == errno.ENOENT:
      return DirectoryListing(directory, False, tuple())
    else:
      raise e


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


def path_stat(project_tree, path_literal):
  path = normpath(path_literal.path)
  ptstat = project_tree.lstat(path)
  if ptstat == None:
    return Stats()

  if ptstat == PTSTAT_FILE:
    return Stats(files=(File(path),))
  elif ptstat == PTSTAT_DIR:
    return Stats(dirs=(Dir(path),))
  elif ptstat == PTSTAT_LINK:
    return Stats(links=(Link(path),))
  else:
    raise ValueError('Unrecognized stat type for {}, {}: {}'.format(project_tree, path, ptstat))


def stat_to_path(stat):
  return Path(stat.path)


def files_content(file_contents):
  """Given a list of FileContent objects, return a FilesContent object."""
  return FilesContent(file_contents)


def file_content(project_tree, path):
  try:
    return FileContent(path.path, project_tree.content(path.path))
  except (IOError, OSError) as e:
    if e.errno == errno.ENOENT:
      return FileContent(path.path, None)
    else:
      raise e


def identity(v):
  return v


Files = Collection.of(File)
Dirs = Collection.of(Dir)
FilesContent = Collection.of(FileContent)
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
  ] + [
    # TODO: These are boilerplatey: aggregation should become native:
    #   see https://github.com/pantsbuild/pants/issues/3169
    (Stats,
     [SelectDependencies(Stats, PathGlobs)],
     merge_stats),
    (Stats,
     [SelectDependencies(Stats, DirectoryListing, field='paths')],
     merge_stats),
    (Files,
     [SelectDependencies(Files, Links)],
     merge_files),
    (Dirs,
     [SelectDependencies(Dirs, Links)],
     merge_dirs),
    (FilesContent,
     [SelectDependencies(FileContent, Files)],
     files_content),
  ]
