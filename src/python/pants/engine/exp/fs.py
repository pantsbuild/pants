# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import fnmatch
from os import sep as os_sep
from os.path import join, normpath

from twitter.common.collections.orderedset import OrderedSet

from pants.base.project_tree import ProjectTree
from pants.engine.exp.selectors import Select, SelectDependencies, SelectLiteral, SelectProjection
from pants.source.wrapped_globs import Globs, RGlobs, ZGlobs, globs_matches
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class Path(datatype('Path', ['path'])):
  """A filesystem path, relative to the ProjectTree's buildroot."""


class Paths(datatype('Paths', ['dependencies'])):
  """A set of Path objects."""


class FileContent(datatype('FileContent', ['path', 'content'])):
  """The content of a file, or None if it did not exist."""

  def __repr__(self):
    content_str = '(len:{})'.format(len(self.content)) if self.content is not None else 'None'
    return 'FileContent(path={}, content={})'.format(self.path, content_str)

  def __str__(self):
    return repr(self)


class FilesContent(datatype('FilesContent', ['dependencies'])):
  """List of FileContent objects."""


def _norm_join(path, paths):
  joined = normpath(join(path, *paths))
  return '' if joined == '.' else joined


class PathGlob(AbstractClass):
  """A filename pattern."""

  _DOUBLE = '**'
  _SINGLE = '*'

  @classmethod
  def create_from_spec(cls, relative_to, filespec):
    return cls._parse_spec(relative_to, filespec.split(os_sep))

  @classmethod
  def _wildcard_part(cls, filespec_parts):
    """Returns the index of the first single-wildcard part in filespec_parts, or None."""
    for i, part in enumerate(filespec_parts):
      if cls._SINGLE in part:
        return i
    return None

  @classmethod
  def _parse_spec(cls, relative_to, parts):
    """Given the path components of a filespec, return a potentially nested PathGlob object.

    TODO: Because `create_from_spec` is called recursively, this method should work harder to
    avoid splitting/joining.
    """
    if cls._DOUBLE in parts:
      raise ValueError('TODO: Unsupported: {}'.format(parts))

    wildcard_index = cls._wildcard_part(parts)
    if wildcard_index is None:
      # A literal path.
      return PathLiteral(_norm_join(relative_to, parts))
    elif wildcard_index == (len(parts) - 1):
      # There is a wildcard in the file basename of the path.
      return PathWildcard(_norm_join(relative_to, parts[:-1]), parts[-1])
    else:
      # There is a wildcard in (at least one of) the dirnames in the path.
      return PathDirWildcard(_norm_join(relative_to, parts[:wildcard_index]),
                             parts[wildcard_index],
                             join(*parts[wildcard_index + 1:]))


class PathLiteral(datatype('PathLiteral', ['path']), PathGlob):
  """A literal path, which may or may not exist.

  This is differentiated from a Path by the fact that a PathLiteral may not exist, while a
  Path must exist.
  """


class PathWildcard(datatype('PathWildcard', ['directory', 'wildcard']), PathGlob):
  """A path with a glob/wildcard in the basename component.

  May match zero or more paths.
  """


class PathDirWildcard(datatype('PathDirWildcard', ['directory', 'wildcard', 'remainder']), PathGlob):
  """A path with a glob/wildcard in a dirname.

  Each PathDirWildcard causes a single directory listing, but the remainder of the path
  may contain additional wildcards, and thus cause additional directory listings.

  May match zero or more paths.
  """


class PathGlobs(datatype('PathGlobs', ['dependencies'])):
  """A set of 'PathGlob' objects.

  This class consumes the (somewhat hidden) support in FilesetWithSpec for normalizing
  globs/rglobs/zglobs into 'filespecs'.
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


class RecursiveSubDirectories(datatype('RecursiveSubDirectories', ['directory', 'dependencies'])):
  """A list of Path objects for recursive subdirectories of the given directory."""


class DirectoryListing(datatype('DirectoryListing', ['directory', 'directories', 'files'])):
  """A list of file and directory Path objects for the given directory."""


def list_directory(project_tree, directory):
  """List Paths directly below the given path, relative to the ProjectTree.

  Returns a DirectoryListing containing directory and file paths relative to the ProjectTree.

  Currently ignores `.`-prefixed subdirectories, but should likely use `--ignore-patterns`.
    TODO: See https://github.com/pantsbuild/pants/issues/2956

  Raises an exception if the path does not exist, or is not a directoy.
  """
  _, subdirs, subfiles = next(project_tree.walk(directory.path))
  return DirectoryListing(directory,
                          [Path(join(directory.path, subdir)) for subdir in subdirs
                           if not subdir.startswith('.')],
                          [Path(join(directory.path, subfile)) for subfile in subfiles])


def recursive_subdirectories(directory, subdirectories_list):
  """Given a directory and a list of RecursiveSubDirectories below it, flatten and return."""
  directories = [directory] + [d for subdir in subdirectories_list for d in subdir.dependencies]
  return RecursiveSubDirectories(directory, directories)


def merge_paths(paths_list):
  generated = set()
  def generate():
    for paths in paths_list:
      for path in paths.dependencies:
        if path in generated:
          continue
        generated.add(path)
        yield path
  return Paths(tuple(generate()))


def filter_file_listing(directory_listing, path_wildcard):
  paths = tuple(f for f in directory_listing.files
                if fnmatch.fnmatch(f.path, path_wildcard.wildcard))
  return Paths(paths)


def filter_dir_listing(directory_listing, path_dir_wildcard):
  """Given a PathDirWildcard, compute a PathGlobs object that encompasses its children.

  The resulting PathGlobs object will be simplified relative to this wildcard, in the sense
  that it will be relative to a subdirectory, with a smaller remainder.
  """
  paths = [join(directory_listing.directory.path, f.path) for f in directory_listing.directories
           if fnmatch.fnmatch(f.path, path_dir_wildcard.wildcard)]
  return PathGlobs(tuple(PathGlob.create_from_spec(p, path_dir_wildcard.remainder) for p in paths))


def file_exists(project_tree, path_literal):
  path = path_literal.path
  return Paths((Path(path),) if project_tree.isfile(path) else ())


def files_content(project_tree, paths):
  contents = []
  for path in paths.dependencies:
    try:
      contents.append(FileContent(path.path, project_tree.content(path.path)))
    except IOError as e:
      if e.errno != errno.ENOENT:
        # Failing to read an existing file is certainly problematic: raise.
        raise e
      # Otherwise, just doesn't exist.
      contents.append(FileContent(path.path, None))
  return FilesContent(contents)


def create_fs_tasks(project_tree_key):
  """Creates tasks that consume the filesystem.

  Many of these tasks are considered "native", and should have their outputs re-validated
  for every build. TODO: They should likely get their own ProductGraph.Node type
  for efficiency/invalidation.
  """
  return [
    # Unfiltered requests for subdirectories.
    (RecursiveSubDirectories,
      [Select(Path),
       SelectDependencies(RecursiveSubDirectories, DirectoryListing, field='directories')],
      recursive_subdirectories),
  ] + [
    # Support for globs.
    (Paths,
      [SelectDependencies(Paths, PathGlobs)],
      merge_paths),
    (Paths,
      [SelectProjection(DirectoryListing, Path, ('directory',), PathWildcard),
       Select(PathWildcard)],
      filter_file_listing),
    (PathGlobs,
      [SelectProjection(DirectoryListing, Path, ('directory',), PathDirWildcard),
       Select(PathDirWildcard)],
      filter_dir_listing),
  ] + [
    # "Native" operations.
    (Paths,
      [SelectLiteral(project_tree_key, ProjectTree),
       Select(PathLiteral)],
      file_exists),
    (FilesContent,
      [SelectLiteral(project_tree_key, ProjectTree),
       Select(Paths)],
      files_content),
    (DirectoryListing,
      [SelectLiteral(project_tree_key, ProjectTree),
       Select(Path)],
      list_directory),
  ]
