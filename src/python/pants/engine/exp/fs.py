# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
from os import sep as os_sep
from os.path import join

from twitter.common.collections.orderedset import OrderedSet

from pants.base.project_tree import ProjectTree
from pants.engine.exp.selectors import Select, SelectDependencies, SelectLiteral
from pants.source.wrapped_globs import Globs, RGlobs, ZGlobs, globs_matches
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


class PathGlob(datatype('PathGlob', ['relative_to', 'path'])):
  """A (potentially recursive) glob that may match zero or more Paths.

  The dependencies of this PathGlob are other PathGlob objects relative to (below) this PathGlob.
  """


class PathGlobs(datatype('PathGlobs', ['dependencies'])):
  """A set of 'filespecs' as produced by FilesetWithSpec.

  This class consumes the (somewhat hidden) support for normalizing globs/rglobs/zglobs
  into 'filespecs'.
  """

  # TODO: regex these.
  _RECURSIVE = os_sep + '**' + os_sep
  _SINGLE = os_sep + '*' + os_sep

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

    path_globs = []
    for filespec in filespecs:
      # TODO: These will be implemented as part of finishing:
      #   https://github.com/pantsbuild/pants/issues/2946
      if cls._RECURSIVE in filespec:
        raise ValueError('TODO: Unsupported: {}'.format(filespec))
      elif cls._SINGLE in filespec:
        raise ValueError('TODO: Unsupported: {}'.format(filespec))
      elif '*' in filespec:
        raise ValueError('TODO: Unsupported: {}'.format(filespec))
      else:
        # A literal path.
        path_globs.append(PathGlob(relative_to, filespec))
    return cls(tuple(path_globs))


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


def file_exists(project_tree, path_glob):
  path = join(path_glob.relative_to, path_glob.path)
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
    # "Native" operations.
    (Paths,
      [SelectDependencies(Paths, PathGlobs)],
      merge_paths),
    (Paths,
      [SelectLiteral(project_tree_key, ProjectTree),
       Select(PathGlob)],
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
