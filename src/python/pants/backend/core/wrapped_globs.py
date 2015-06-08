# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from copy import deepcopy

from six import string_types
from twitter.common.dirutil.fileset import Fileset

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import deprecated


class FilesetWithSpec(object):
  """A set of files with that keeps track of how we got it.

  The filespec is what globs or file list it came from.
  """
  def __init__(self, rel_root, result, filespec):
    self._rel_root = rel_root
    self._result = result
    self.filespec = filespec

  def __iter__(self):
    return self._result.__iter__()

  def __getitem__(self, index):
    return self._result[index]

  @deprecated(removal_version='0.0.35',
              hint_message='Instead of globs(a) + globs(b), use globs(a, b)')
  def __add__(self, other):
    filespec = deepcopy(self.filespec)
    if isinstance(other, FilesetWithSpec):
      filespec['globs'] += other.filespec['globs']
      other_result = other._result
    else:
      filespec['globs'] += [os.path.join(self._rel_root, other_path) for other_path in other]
      other_result = other
    result = list(set(self._result).union(set(other_result)))
    return FilesetWithSpec(self._rel_root, result, filespec)

  @deprecated(removal_version='0.0.35',
              hint_message='Instead of glob arithmetic, use glob(..., exclude=[...])')
  def __sub__(self, other):
    filespec = deepcopy(self.filespec)
    exclude = filespec.get('exclude', [])
    if isinstance(other, FilesetWithSpec):
      exclude.append(other.filespec)
      other_result = other._result
    else:
      exclude.append({'globs' : [os.path.join(self._rel_root, other_path) for other_path in other]})
      other_result = other
    filespec['exclude'] = exclude
    result = list(set(self._result) - set(other_result))
    return FilesetWithSpec(self._rel_root, result, filespec)

class FilesetRelPathWrapper(object):
  def __init__(self, parse_context):
    self.rel_path = parse_context.rel_path

  def __call__(self, *args, **kwargs):
    root = os.path.join(get_buildroot(), self.rel_path)

    excludes = kwargs.pop('exclude', [])
    if isinstance(excludes, string_types):
        raise ValueError("Expected exclude parameter to be a list of globs, lists, or strings")

    for i, exclude in enumerate(excludes):
      if isinstance(exclude, string_types):
        # You can't subtract raw strings from globs
        excludes[i] = [exclude]

    for glob in args:
      if(self._is_glob_dir_outside_root(glob, root)):
        raise ValueError('Invalid glob {}, points outside BUILD file root dir {}'.format(glob, root))

    result = self.wrapped_fn(root=root, *args, **kwargs)

    for exclude in excludes:
      result -= exclude

    buildroot = get_buildroot()
    rel_root = os.path.relpath(root, buildroot)
    filespec = self.to_filespec(args, root=rel_root, excludes=excludes)
    return FilesetWithSpec(rel_root, result, filespec)

  def _is_glob_dir_outside_root(self, glob, root):
    # The assumption is that a correct glob starts with the root,
    # even after normalizing.
    glob_path = os.path.normpath(os.path.join(root, glob))

    # Check if the glob path has the correct root.
    return os.path.commonprefix([root, glob_path]) != root

  def to_filespec(self, args, root='', excludes=None):
    """Return a dict representation of this glob list, relative to the buildroot.

    The format of the dict is {'globs': [ 'list', 'of' , 'strings' ]
                    (optional) 'exclude' : [{'globs' : ... }, ...] }

    The globs are in zglobs format.
    """
    result = {'globs' : [os.path.join(root, arg) for arg in args]}
    if excludes:
      result['exclude'] = []
      for exclude in excludes:
        if hasattr(exclude, 'filespec'):
          result['exclude'].append(exclude.filespec)
        else:
          result['exclude'].append({'globs' : [os.path.join(root, x) for x in exclude]})
    return result

class Globs(FilesetRelPathWrapper):
  """Returns Fileset containing matching files in same directory as this BUILD file.
  E.g., ``sources = globs('*java'),`` to get .java files in this directory.

  :param exclude: a list of {,r,z}globs objects, strings, or lists of
  strings to exclude.  E.g. ``globs('*',exclude=[globs('*.java'),
  'foo.py'])`` gives all files in this directory except ``.java``
  files and ``foo.py``.

  Deprecated:
  You might see that old code uses "math" on the return value of
  ``globs()``.  E.g., ``globs('*') - globs('*.java')`` gives all files
  in this directory *except* ``.java`` files.  Please use exclude
  instead, since pants is moving to make BUILD files easier to parse,
  and the new grammar will not support arithmetic.

  :returns FilesetWithSpec containing matching files in same directory as this BUILD file.
  :rtype FilesetWithSpec

  """
  wrapped_fn = Fileset.globs


class RGlobs(FilesetRelPathWrapper):
  """Recursive ``globs``, returns Fileset matching files in this directory and its descendents.

  E.g., ``bundle(fileset=rglobs('config/*')),`` to bundle up all files in
  the config, config/foo, config/foo/bar directories.

  :param exclude: a list of {,r,z}globs objects, strings, or lists of
  strings to exclude.  E.g. ``rglobs('config/*',exclude=[globs('config/*.java'),
  'config/foo.py'])`` gives all files under config except ``.java`` files and ``config/foo.py``.

  Deprecated:
  You might see that old code uses "math" on the return value of ``rglobs()``. E.g.,
  ``rglobs('config/*') - rglobs('config/foo/*')`` gives all files under `config` *except*
  those in ``config/foo``.  Please use exclude instead, since pants is moving to
  make BUILD files easier to parse, and the new grammar will not support arithmetic.
  :returns FilesetWithSpec matching files in this directory and its descendents.
  :rtype FilesetWithSpec
  """
  @staticmethod
  def rglobs_following_symlinked_dirs_by_default(*globspecs, **kw):
    if 'follow_links' not in kw:
      kw['follow_links'] = True
    return Fileset.rglobs(*globspecs, **kw)

  wrapped_fn = rglobs_following_symlinked_dirs_by_default

  def to_filespec(self, args, root='', excludes=None):
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
          out.append(component)
        elif component[0] == '*':
          out.append('**/' + component)
        else:
          out.append(component)

      def rglob_path(beginning, rest):
        if not rest:
          return [beginning]
        endings = []
        for i, item in enumerate(rest):
          if beginning:
            beginning += os.path.sep
          if item.startswith('**'):
            for ending in rglob_path(beginning + item, rest[i+1:]):
              endings.append(ending)
            for ending in rglob_path(beginning + item[3:], rest[i+1:]):
              endings.append(ending)
            return endings
          else:
            if beginning:
              beginning += os.path.sep + item
            else:
              beginning = item

        return [beginning]

      rglobs.extend(rglob_path('', out))

    return super(RGlobs, self).to_filespec(rglobs, root=root, excludes=excludes)

class ZGlobs(FilesetRelPathWrapper):
  """Returns a FilesetWithSpec that matches zsh-style globs, including ``**/`` for recursive globbing.

  Uses ``BUILD`` file's directory as the "working directory".
  """
  @staticmethod
  def zglobs_following_symlinked_dirs_by_default(*globspecs, **kw):
    if 'follow_links' not in kw:
      kw['follow_links'] = True
    return Fileset.zglobs(*globspecs, **kw)

  wrapped_fn = zglobs_following_symlinked_dirs_by_default
