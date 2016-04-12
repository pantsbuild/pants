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
    return super(Path, cls).__new__(cls, normpath(six.text_type(path)))


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
    return super(Link, cls).__new__(cls, six.text_type(path))


class Paths(datatype('Paths', ['dependencies'])):
  """A set of Path objects."""


class Stats(datatype('Stats', ['files', 'dirs', 'links'])):
  """Sets of File, Dir, and Link objects."""

  def __new__(cls, files=tuple(), dirs=tuple(), links=tuple()):
    return super(Stats, cls).__new__(cls, files, dirs, links)


class Files(datatype('Files', ['dependencies'])):
  """A set of File objects."""


class Dirs(datatype('Dirs', ['dependencies'])):
  """A set of Dir objects."""


class Links(datatype('Links', ['dependencies'])):
  """A set of Link objects."""


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
  def create_from_spec(cls, ftype, relative_to, filespec):
    """Given a filespec, return a potentially nested PathGlob object.

    TODO: Because `create_from_spec` is called recursively, this method should work harder to
    avoid splitting/joining. Optimization needed.
    """
    parts = _norm_with_dir(filespec).split(os_sep)
    print('parsing for {} and {}'.format(relative_to, parts))
    double_index, single_index = cls._wildcard_part(parts)
    if double_index is not None:
      # There is a double-wildcard in a dirname of the path: double wildcards are recursive,
      # so there are two remainder possibilities: one with the double wildcard included, and the
      # other without.
      remainders = (join(*parts[double_index+1:]), join(*parts[double_index:]))
      return PathDirWildcard(ftype,
                             join(relative_to, *parts[:double_index]),
                             parts[double_index],
                             remainders)
    elif single_index is None:
      # A literal path.
      return PathLiteral(ftype, join(relative_to, *parts))
    elif single_index == (len(parts) - 1):
      # There is a wildcard in the file basename of the path.
      return PathWildcard(ftype, join(relative_to, *parts[:-1]), parts[-1])
    else:
      # There is a wildcard in (at least one of) the dirnames in the path.
      remainders = (join(*parts[single_index + 1:]),)
      return PathDirWildcard(ftype,
                             join(relative_to, *parts[:single_index]),
                             parts[single_index],
                             remainders)


class PathLiteral(datatype('PathLiteral', ['ftype', 'path']), PathGlob):
  """A single literal PathGlob, which may or may not exist."""


class PathWildcard(datatype('PathWildcard', ['ftype', 'directory', 'wildcard']), PathGlob):
  """A PathGlob with a wildcard in the basename component."""


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
    print('>>> listing {}: got {}'.format(path, entries))
    return DirectoryListing(directory,
                            True,
                            tuple(Path(e) for e in entries))
  except (IOError, OSError) as e:
    if e.errno == errno.ENOENT:
      return DirectoryListing(directory, False, tuple())
    else:
      raise e


def merge_stats(stats_list):
  """Merge Stats lists.

  TODO: This is boilerplatey: aggregation should become native:
   see https://github.com/pantsbuild/pants/issues/3169
  """
  def generate(field):
    for stats in stats_list:
      for stat in getattr(stats, field):
        yield stat
  return Stats(files=tuple(generate('files')),
               dirs=tuple(generate('dirs')),
               links=tuple(generate('links')))


def apply_path_wildcard(stats, path_wildcard):
  """Filter the given Stats object using the given PathWildcard."""
  def filtered(ftype, entries):
    return tuple(stat for stat in entries
                 if type(stat) == ftype and
                 fnmatch.fnmatch(stat.path, path_wildcard.wildcard))
  coltype = path_wildcard.ftype
  if coltype is Files:
    return Stats(files=filtered(File, stats.files))
  elif coltype is Dirs:
    return Stats(dirs=filtered(Dir, stats.dirs))
  elif coltype is Links:
    return Stats(links=filtered(Link, stats.links))
  else:
    raise ValueError('Unrecognized Stat type: {}'.format(coltype))


def apply_path_literal(stats, path_literal):
  """Filter the given Stats object using the given PathLiteral."""
  raise ValueError('Not implemented.')


def apply_path_dir_wildcard(dirs, path_dir_wildcard):
  """Given a PathDirWildcard, compute a PathGlobs object that encompasses its children.

  The resulting PathGlobs object will be simplified relative to this wildcard, in the sense
  that it will be relative to a subdirectory.
  """
  ftype = path_dir_wildcard.ftype
  paths = [d.path for d in dirs.dependencies
           if fnmatch.fnmatch(d.path, path_dir_wildcard.wildcard)]
  print('>>> path dir wildcard {}'.format(path_dir_wildcard))
  return PathGlobs(ftype, tuple(PathGlob.create_from_spec(ftype, p, remainder)
                                for p in paths
                                for remainder in path_dir_wildcard.remainders))


def resolve_dir_links(direct_stats, linked_dirs):
  return Dirs(tuple(d for dirs in (direct_stats.dirs, linked_dirs.dependencies) for d in dirs))


def resolve_file_links(direct_stats, linked_files):
  return Files(tuple(f for files in (direct_stats.files, linked_files.dependencies) for f in files))


def merge_dirs(dirs_list):
  return Dirs(tuple(d for dirs in dirs_list for d in dirs))


def merge_files(files_list):
  return Files(tuple(f for files in files_list for f in files))


def read_link(project_tree, link):
  raise ValueError('Not implemented')


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


def stats_to_paths(stats):
  return Paths(tuple(Path(s.path)
                     for col in (stats.files, stats.dirs, stats.links)
                     for s in col))


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
    # Execute globs.
    (Stats,
     [SelectProjection(Stats, Dir, ('directory',), PathWildcard),
      Select(PathWildcard)],
     apply_path_wildcard),
    (PathGlobs,
     [SelectProjection(Dirs, Dir, ('directory',), PathDirWildcard),
      Select(PathDirWildcard)],
     apply_path_dir_wildcard),
    (Stats,
     [SelectProjection(Stats, Path, ('path',), PathLiteral)],
     # TODO: need to filter to ftype
     apply_path_literal),
    (Paths,
     [Select(Stats)],
     stats_to_paths),
  ] + [
    # Link resolution.
    (Dirs,
     [Select(Stats),
      SelectProjection(Dirs, Links, ('links',), Stats)],
     resolve_dir_links),
    (Dirs,
     [SelectDependencies(Dirs, Links)],
     merge_dirs),
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
    (Files,
     [SelectDependencies(Files, Links)],
     merge_files),
  ] + [
    # TODO: unclassified.
    (Stats,
     [SelectDependencies(Stats, PathGlobs)],
     merge_stats),
    (Stats,
     [SelectDependencies(Stats, DirectoryListing, field='paths')],
     merge_stats),
  ] + [
    # Retrieve the contents of Files.
    (FilesContent,
     [SelectDependencies(FileContent, Files)],
     files_content),
  ]
