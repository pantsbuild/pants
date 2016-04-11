# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import fnmatch
from abc import abstractproperty
from os import sep as os_sep
from os.path import join, normpath

import six
from twitter.common.collections.orderedset import OrderedSet

from pants.base.project_tree import PTSTAT_DIR, PTSTAT_FILE, PTSTAT_LINK
from pants.engine.exp.selectors import Select, SelectDependencies, SelectProjection
from pants.source.wrapped_globs import Globs, RGlobs, ZGlobs
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class Path(datatype('Path', ['path'])):
  """A potentially non-existent filesystem path, relative to the ProjectTree's buildroot."""

  def __new__(cls, path):
    return super(Path, cls).__new__(cls, six.text_type(path))


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


class Paths(datatype('Paths', ['dependencies'])):
  """A set of Path objects."""


class Stats(datatype('Stats', ['dependencies'])):
  """A set of Stat objects."""


class Dirs(datatype('Dirs', ['dependencies'])):
  """A set of Dir objects."""


class FileContent(datatype('FileContent', ['path', 'content'])):
  """The content of a file, or None if it did not exist."""

  def __repr__(self):
    content_str = '(len:{})'.format(len(self.content)) if self.content is not None else 'None'
    return 'FileContent(path={}, content={})'.format(self.path, content_str)

  def __str__(self):
    return repr(self)


class FilesContent(datatype('FilesContent', ['dependencies'])):
  """List of FileContent objects."""


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

  All PathGlob subclasses match zero or more paths, which differentiates them from Path
  objects, which are expected to represent literal existing files.
  """

  _DOUBLE = '**'
  _SINGLE = '*'

  @classmethod
  def create_from_spec(cls, relative_to, filespec):
    return cls._parse_spec(relative_to, _norm_with_dir(filespec).split(os_sep))

  @classmethod
  def _wildcard_part(cls, filespec_parts):
    """Returns the index of the first double-wildcard or single-wildcard part in filespec_parts.

    Only the first value of either kind will be returned, so at least one entry in the tuple will
    always be None.
    """
    for i, part in enumerate(filespec_parts):
      if cls._DOUBLE in part:
        if part != cls._DOUBLE:
          raise ValueError(
              'Illegal component "{}" in filespec: {}'.format(part, join(*filespec_parts)))
        return i, None
      elif cls._SINGLE in part:
        return None, i
    return None, None

  @classmethod
  def _parse_spec(cls, relative_to, parts):
    """Given the path components of a filespec, return a potentially nested PathGlob object.

    TODO: Because `create_from_spec` is called recursively, this method should work harder to
    avoid splitting/joining. Optimization needed.
    """
    double_index, single_index = cls._wildcard_part(parts)
    if double_index is not None:
      # There is a double-wildcard in a dirname of the path: double wildcards are recursive,
      # so there are two remainder possibilities: one with the double wildcard included, and the
      # other without.
      remainders = (join(*parts[double_index+1:]), join(*parts[double_index:]))
      return PathDirWildcard(join(relative_to, *parts[:double_index]),
                             parts[double_index],
                             remainders)
    elif single_index is None:
      # A literal path.
      return PathLiteral(join(relative_to, *parts))
    elif single_index == (len(parts) - 1):
      # There is a wildcard in the file basename of the path.
      return PathWildcard(join(relative_to, *parts[:-1]), parts[-1])
    else:
      # There is a wildcard in (at least one of) the dirnames in the path.
      remainders = (join(*parts[single_index + 1:]),)
      return PathDirWildcard(join(relative_to, *parts[:single_index]),
                             parts[single_index],
                             remainders)


class PathLiteral(datatype('PathLiteral', ['path']), PathGlob):
  """A single literal PathGlob, which may or may not exist."""


class PathWildcard(datatype('PathWildcard', ['directory', 'wildcard']), PathGlob):
  """A PathGlob with a wildcard in the basename component."""


class PathDirWildcard(datatype('PathDirWildcard', ['directory', 'wildcard', 'remainders']), PathGlob):
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

    TODO: This currently sortof-executes parsing via 'to_filespec'. Should maybe push that out to
    callers to make them deal with errors earlier.

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
    return cls(tuple(PathGlob.create_from_spec(relative_to, filespec) for filespec in filespecs))


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
    path = directory.path
    return DirectoryListing(directory,
                            True,
                            [Path(join(path, e)) for e in project_tree.listdir(path)])
  except (IOError, OSError) as e:
    if e.errno == errno.ENOENT:
      return DirectoryListing(directory, False, [])
    else:
      raise e


def merge_dir_stats(stats_list):
  return merge_stats(stats_list, ftype=Dir, result_type=Dirs)


def merge_stats(stats_list, ftype=None, result_type=Stats):
  """Merge and filter Stats lists.

  TODO: This is boilerplatey: it's half aggregation / half conversion. The
  aggregation bit should become native:
   see https://github.com/pantsbuild/pants/issues/3169
  """
  generated = set()
  def generate():
    for stats in stats_list:
      for stat in stats.dependencies:
        if ftype and not type(stat) == ftype:
          continue
        if stat.path in generated:
          # TODO: remove this validation... unclear how it would happen.
          raise ValueError('Duplicate path in {}'.format(stats_list))
        generated.add(stat.path)
        yield stat
  return result_type(tuple(generate()))


def stats_to_paths(stats):
  return Paths(tuple(Path(stat.path) for stat in stats.dependencies))


def apply_path_wildcard(stats, path_wildcard):
  """Filter the given Stats object using the given PathWildcard."""
  ftype = Dir if path_wildcard.wildcard.endswith(os_sep + '.') else File
  filtered = tuple(stat for stat in stats.dependencies
                   if type(stat) == ftype and
                   fnmatch.fnmatch(stat.path, path_wildcard.wildcard))
  return Stats(filtered)


def apply_path_dir_wildcard(stats, path_dir_wildcard):
  """Given a PathDirWildcard, compute a PathGlobs object that encompasses its children.

  The resulting PathGlobs object will be simplified relative to this wildcard, in the sense
  that it will be relative to a subdirectory.
  """
  paths = [stat.path for stat in stats.dependencies
           if type(stat) == Dir and
           fnmatch.fnmatch(stat.path, path_dir_wildcard.wildcard)]
  return PathGlobs(tuple(PathGlob.create_from_spec(p, remainder)
                         for p in paths
                         for remainder in path_dir_wildcard.remainders))


def path_stat(project_tree, path_literal):
  path = path_literal.path
  ptstat = project_tree.lstat(path)
  if ptstat == None:
    return Stats(tuple())

  if ptstat == PTSTAT_FILE:
    return Stats((File(path),))
  elif ptstat == PTSTAT_DIR:
    return Stats((Dir(path),))
  elif ptstat == PTSTAT_LINK:
    return Stats((Link(path),))
  else:
    raise ValueError('Unrecognized stat type for {}, {}: {}'.format(project_tree, path, ptstat))


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


def create_fs_tasks():
  """Creates tasks that consume the native filesystem Node type."""
  return [
    (Stats,
     [SelectProjection(Stats, Dir, ('directory',), PathWildcard),
      Select(PathWildcard)],
     apply_path_wildcard),
    (PathGlobs,
     [SelectProjection(Stats, Dir, ('directory',), PathDirWildcard),
      Select(PathDirWildcard)],
     apply_path_dir_wildcard),
    (Paths,
     [Select(Stats)],
     stats_to_paths),
    (Dirs,
     [SelectDependencies(Stats, PathGlobs)],
     merge_dir_stats),
    (Stats,
     [SelectDependencies(Stats, PathGlobs)],
     merge_stats),
    (Stats,
     [SelectDependencies(Stats, DirectoryListing, field='paths')],
     merge_stats),
    (FilesContent,
     [SelectDependencies(FileContent, Paths)],
     files_content),
    (Stats,
     [SelectProjection(Stats, Path, ('path',), PathLiteral)],
     identity),
  ]
