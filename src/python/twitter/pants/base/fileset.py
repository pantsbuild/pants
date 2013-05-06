# ==================================================================================================
# Copyright 2012 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import fnmatch
import glob
import os
import re

from twitter.common.lang import Compatibility


def fnmatch_translate_extended(pat):
  """
     A modified version of fnmatch.translate to match zsh semantics more closely:
       '*' matches one or more characters instead of zero or more
       '**' is equivalent to '*'
       '**/' matches one or more directories.
     E.g. src/**/*.py => match all files ending with .py in any subdirectory of src/
  """
  i, n = 0, len(pat)
  res = ''
  while i < n:
    c = pat[i]
    i += 1
    if c == '*':
      if pat[i:i+2] == '*/':
        res += '([^/]+/)*'
        i += 2
      elif pat[i:i+1] == '*':
        res += '([^/]+)'
        i += 1
      else:
        res += '([^/]+)'
    elif c == '?':
      res += '.'
    elif c == '[':
      j = i
      if j < n and pat[j] == '!':
        j += 1
      if j < n and pat[j] == ']':
        j += 1
      while j < n and pat[j] != ']':
        j += 1
      if j >= n:
        res += '\\['
      else:
        stuff = pat[i:j].replace('\\', '\\\\')
        i = j + 1
        if stuff[0] == '!':
          stuff = '^' + stuff[1:]
        elif stuff[0] == '^':
          stuff = '\\' + stuff
        res += '[' + stuff + ']'
    else:
      res += re.escape(c)
  return res + '\Z(?ms)'


class Fileset(object):
  """
    An iterable, callable object that will gather up a set of files lazily when iterated over or
    called.  Supports unions with iterables, other Filesets and individual items using the ^ and +
    operators as well as set difference using the - operator.
  """

  @classmethod
  def walk(cls, path=None, allow_dirs=False, follow_links=False):
    """Walk the directory tree starting at path, or os.curdir if None.  If
       allow_dirs=False, iterate only over files.  If allow_dirs=True,
       iterate over both files and directories.  If follow_links=True symlinked
       directories will be traversed.
    """
    path = path or os.curdir
    for root, dirs, files in os.walk(path, followlinks=follow_links):
      if allow_dirs:
        for dirname in dirs:
          base_dir = os.path.relpath(os.path.normpath(os.path.join(root, dirname)), path)
          yield base_dir
          yield base_dir + os.sep
      for filename in files:
        yield os.path.relpath(os.path.normpath(os.path.join(root, filename)), path)

  @classmethod
  def globs(cls, *globspecs, **kw):
    """Returns a Fileset that combines the lists of files returned by
       glob.glob for each globspec.  rcfiles starting with '.' are not
       returned unless explicitly globbed.  For example, ".*" matches
       ".bashrc" but "*" does not, mirroring the semantics of 'ls' without
       '-a'.

       Walks the current working directory by default, can be overrided with
       the 'root' keyword argument.
    """
    root = kw.pop('root', os.curdir)
    def relative_glob(globspec):
      for fn in glob.glob(os.path.join(root, globspec)):
        yield os.path.relpath(fn, root)
    def combine(files, globspec):
      return files ^ set(relative_glob(globspec))
    return cls(lambda: reduce(combine, globspecs, set()))

  @classmethod
  def _do_rglob(cls, matcher, root, **kw):
    for path in cls.walk(root, **kw):
      if matcher(path):
        yield path

  @classmethod
  def rglobs(cls, *globspecs, **kw):
    """Returns a Fileset that containing the union of all files matched by the
       globspecs applied at each directory beneath the root.  By default the
       root is the current working directory, but can be overridden with the
       'root' keyword argument.  Unlike Fileset.globs, rcfiles are matched
       by '*' (e.g.  ".bashrc"), matching the semantics of 'ls -a'.
    """
    root = kw.pop('root', os.curdir)
    def matcher(path):
      for globspec in globspecs:
        if fnmatch.fnmatch(path, globspec):
          return True
    return cls(lambda: set(cls._do_rglob(matcher, allow_dirs=False, root=root, **kw)))

  @classmethod
  def zglobs(cls, *globspecs, **kw):
    """Returns a Fileset that matches zsh-style globs, including '**/' for recursive globbing.

       By default searches from the current working directory.  Can be overridden with the
       'root' keyword argument.
    """
    root = kw.pop('root', os.curdir)
    patterns = [re.compile(fnmatch_translate_extended(spec)) for spec in globspecs]
    def matcher(path):
      for pattern in patterns:
        if pattern.match(path):
          return True
    return cls(lambda: set(cls._do_rglob(matcher, allow_dirs=True, root=root, **kw)))

  def __init__(self, callable_):
    self._callable = callable_

  def __call__(self, *args, **kwargs):
    return self._callable(*args, **kwargs)

  def __iter__(self):
    return iter(self())

  def __add__(self, other):
    return self ^ other

  def __xor__(self, other):
    def union():
      if callable(other):
        return self() ^ other()
      elif isinstance(other, set):
        return self() ^ other
      elif isinstance(other, Compatibility.string):
        raise TypeError('Unsupported operand type (%r) for ^: %r and %r' %
                        (type(other), self, other))
      else:
        try:
          return self() ^ set(iter(other))
        except TypeError:
          return self().add(other)
    return Fileset(union)

  def __sub__(self, other):
    def subtract():
      if callable(other):
        return self() - other()
      elif isinstance(other, set):
        return self() - other
      elif isinstance(other, Compatibility.string):
        raise TypeError('Unsupported operand type (%r) for -: %r and %r' %
                        (type(other), self, other))
      else:
        try:
          return self() - set(iter(other))
        except TypeError:
          return self().remove(other)
    return Fileset(subtract)
