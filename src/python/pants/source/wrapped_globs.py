# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import fnmatch
import os

from six import string_types
from twitter.common.dirutil.fileset import Fileset

from pants.base.build_environment import get_buildroot
from pants.util.memo import memoized_property


def globs_matches(path, patterns):
  return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def matches_filespec(path, spec):
  if spec is None:
    return False
  if not globs_matches(path, spec.get('globs', [])):
    return False
  for spec in spec.get('exclude', []):
    if matches_filespec(path, spec):
      return False
  return True


class FilesetWithSpec(object):
  """A set of files that keeps track of how we got it.

  The filespec is what globs or file list it came from.
  """

  def __init__(self, rel_root, filespec, files_calculator):
    self._rel_root = rel_root
    self.filespec = filespec
    self._files_calculator = files_calculator

  @memoized_property
  def files(self):
    return self._files_calculator()

  def __iter__(self):
    return self.files.__iter__()

  def __getitem__(self, index):
    return self.files[index]


class FilesetRelPathWrapper(object):
  KNOWN_PARAMETERS = frozenset(['exclude', 'follow_links'])

  wrapped_fn = None   # Subclasses must override.

  def __init__(self, parse_context):
    """
    :param parse_context: The BUILD file parse context.
    """
    self._rel_path = parse_context.rel_path

  def __call__(self, *patterns, **kwargs):
    """
    :param patterns: glob patterns to apply.
    :param exclude: A list of {,r,z}globs objects, strings, or lists of strings to exclude.
    """
    root = os.path.normpath(os.path.join(get_buildroot(), self._rel_path))

    raw_excludes = kwargs.pop('exclude', [])
    if isinstance(raw_excludes, string_types):
      raise ValueError("Expected exclude parameter to be a list of globs, lists, or strings")

    # You can't subtract raw strings from globs
    def ensure_string_wrapped_in_list(element):
      if isinstance(element, string_types):
        return [element]
      else:
        return element

    excludes = [ensure_string_wrapped_in_list(exclude) for exclude in raw_excludes]

    # making sure there are no unknown arguments.
    unknown_args = set(kwargs.keys()) - self.KNOWN_PARAMETERS

    if unknown_args:
      raise ValueError('Unexpected arguments while parsing globs: {}'.format(
        ', '.join(unknown_args)))

    for glob in patterns:
      if self._is_glob_dir_outside_root(glob, root):
        raise ValueError('Invalid glob {}, points outside BUILD file root {}'.format(glob, root))

    def files_calculator():
      result = self.wrapped_fn(root=root, *patterns, **kwargs)

      for ex in excludes:
        result -= ex

      return result

    buildroot = get_buildroot()
    rel_root = os.path.relpath(root, buildroot)
    if rel_root == '.':
      rel_root = ''
    filespec = self.to_filespec(patterns, root=rel_root, excludes=excludes)
    return FilesetWithSpec(rel_root, filespec, files_calculator)

  @staticmethod
  def _is_glob_dir_outside_root(glob, root):
    # The assumption is that a correct glob starts with the root,
    # even after normalizing.
    glob_path = os.path.normpath(os.path.join(root, glob))

    # Check if the glob path has the correct root.
    return os.path.commonprefix([root, glob_path]) != root

  @classmethod
  def to_filespec(cls, args, root='', excludes=None):
    """Return a dict representation of this glob list, relative to the buildroot.

    The format of the dict is {'globs': [ 'list', 'of' , 'strings' ]
                    (optional) 'exclude' : [{'globs' : ... }, ...] }

    The globs are in zglobs format.
    """
    result = {'globs': [os.path.join(root, arg) for arg in args]}
    if excludes:
      result['exclude'] = []
      for exclude in excludes:
        if hasattr(exclude, 'filespec'):
          result['exclude'].append(exclude.filespec)
        else:
          result['exclude'].append({'globs': [os.path.join(root, x) for x in exclude]})
    return result


class Globs(FilesetRelPathWrapper):
  """Matches files in the BUILD file's directory.

  E.g., - ``sources = globs('*java'),`` to get .java files in this directory.
        - ``globs('*',exclude=[globs('*.java'), 'foo.py'])`` to get all files in this directory
          except ``.java`` files and ``foo.py``.
  """
  wrapped_fn = Fileset.globs


class RGlobs(FilesetRelPathWrapper):
  """Matches files recursively under the BUILD file's directory.

  E.g., ``bundle(fileset=rglobs('config/*'))`` to bundle up all files in the config,
        config/foo, config/foo/bar directories.
  """

  @staticmethod
  def rglobs_following_symlinked_dirs_by_default(*globspecs, **kw):
    if 'follow_links' not in kw:
      kw['follow_links'] = True
    return Fileset.rglobs(*globspecs, **kw)

  wrapped_fn = rglobs_following_symlinked_dirs_by_default

  @classmethod
  def to_filespec(cls, args, root='', excludes=None):
    # In rglobs, * at the beginning of a path component means "any
    # number of directories, including 0".  Unfortunately, "**" in
    # some other systems, e.g. git means "one or more directories".
    # So every time we see ^* or **, we need to output both
    # "**/whatever" and "whatever".
    rglobs = []
    for arg in args:
      components = arg.split(os.path.sep)
      out = []
      for component in components:
        if component == '**':
          if out and out[-1].startswith("**"):
            continue
          out.append(component)
        elif component[0] == '*':
          if out and out[-1].startswith("**"):
            # We want to translate **/*.py to **/*.py, not **/**/*.py
            out.append(component)
          else:
            out.append('**/' + component)
        else:
          out.append(component)

      def rglob_path(beginning, rest):
        if not rest:
          return [beginning]
        endings = []
        for i, item in enumerate(rest):
          if beginning and not beginning.endswith(os.path.sep):
            beginning += os.path.sep
          if item.startswith('**'):
            # .../**/*.java
            for ending in rglob_path(beginning + item, rest[i + 1:]):
              endings.append(ending)
            # .../*.java
            for ending in rglob_path(beginning + item[3:], rest[i + 1:]):
              endings.append(ending)
            return endings
          else:
            if beginning and not beginning.endswith(os.path.sep):
              beginning += os.path.sep + item
            else:
              beginning += item

        return [beginning]

      rglobs.extend(rglob_path('', out))

    return super(RGlobs, cls).to_filespec(rglobs, root=root, excludes=excludes)


class ZGlobs(FilesetRelPathWrapper):
  """Matches files in the BUILD file's dir using zsh-style globs, including ``**/`` to recurse."""

  @staticmethod
  def zglobs_following_symlinked_dirs_by_default(*globspecs, **kw):
    if 'follow_links' not in kw:
      kw['follow_links'] = True
    return Fileset.zglobs(*globspecs, **kw)

  wrapped_fn = zglobs_following_symlinked_dirs_by_default
