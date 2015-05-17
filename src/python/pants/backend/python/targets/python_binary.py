# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.pex_info import PexInfo
from six import string_types
from twitter.common.collections import maybe_list

from pants.backend.python.targets.python_target import PythonTarget
from pants.base.exceptions import TargetDefinitionException


class PythonBinary(PythonTarget):
  """Produces a Python binary.

  Python binaries are pex files, self-contained executable shell
  scripts that contain a complete Python environment capable of
  running the target. For more information about pex files see
  http://pantsbuild.github.io/python-readme.html#how-pex-files-work.
  """

  # TODO(wickman) Consider splitting pex options out into a separate PexInfo builder that can be
  # attached to the binary target.  Ideally the PythonBinary target is agnostic about pex mechanics
  def __init__(self,
               source=None,
               entry_point=None,
               inherit_path=False,        # pex option
               zip_safe=True,             # pex option
               always_write_cache=False,  # pex option
               repositories=None,         # pex option
               indices=None,              # pex option
               ignore_errors=False,       # pex option
               platforms=(),
               **kwargs):
    """
    :param source: relative path to one python source file that becomes this
      binary's __main__.
      If None specified, drops into an interpreter by default.
    :param string entry_point: the default entry point for this binary.  if None, drops into the entry
      point that is defined by source. Something like
      "pants.bin.pants_exe:main", where "pants.bin.pants_exe" is the package
      name and "main" is the function name (if ommitted, the module is
      executed directly, presuming it has a ``__main.py__``).
    :param sources: Overridden by source. To specify more than one source file,
      use a python_library and have the python_binary depend on that library.
    :param inherit_path: inherit the sys.path of the environment that this binary runs in
    :param zip_safe: whether or not this binary is safe to run in compacted (zip-file) form
    :param always_write_cache: whether or not the .deps cache of this PEX file should always
      be written to disk.
    :param repositories: a list of repositories to query for dependencies.
    :param indices: a list of indices to use for packages.
    :param ignore_errors: should we ignore inability to resolve dependencies?
    :param platforms: extra platforms to target when building this binary. If this is, e.g.,
      ``['current', 'linux-x86_64', 'macosx-10.4-x86_64']``, then when building the pex, then
      for any platform-dependent modules, Pants will include ``egg``\s for Linux (64-bit Intel),
      Mac OS X (version 10.4 or newer), and the current platform (whatever is being used when
      making the PEX).
    :param compatibility: either a string or list of strings that represents
      interpreter compatibility for this target, using the Requirement-style format,
      e.g. ``'CPython>=3', or just ['>=2.7','<3']`` for requirements agnostic to interpreter class.
    """

    sources = [] if source is None else [source]
    super(PythonBinary, self).__init__(sources=sources, **kwargs)

    if source is None and entry_point is None:
      raise TargetDefinitionException(self,
          'A python binary target must specify either source or entry_point.')

    if not isinstance(platforms, (list, tuple)) and not isinstance(platforms, string_types):
      raise TargetDefinitionException(self, 'platforms must be a list, tuple or string.')

    # TODO(pl): Most if not all of these should live in payload fields
    self._entry_point = entry_point
    self._inherit_path = bool(inherit_path)
    self._zip_safe = bool(zip_safe)
    self._always_write_cache = bool(always_write_cache)
    self._repositories = maybe_list(repositories or [])
    self._indices = maybe_list(indices or [])
    self._ignore_errors = bool(ignore_errors)
    self._platforms = tuple(maybe_list(platforms or []))

    if source and entry_point:
      entry_point_module = entry_point.split(':', 1)[0]
      entry_source = list(self.sources_relative_to_source_root())[0]
      source_entry_point = self._translate_to_entry_point(entry_source)
      if entry_point_module != source_entry_point:
        raise TargetDefinitionException(self,
            'Specified both source and entry_point but they do not agree: {} vs {}'.format(
            source_entry_point, entry_point_module))

  @property
  def platforms(self):
    return self._platforms

  # TODO(wickman) These should likely be attributes on PythonLibrary targets
  # and not PythonBinary targets, or at the very worst, both.
  @property
  def repositories(self):
    return self._repositories

  @property
  def indices(self):
    return self._indices

  def _translate_to_entry_point(self, source):
    source_base, _ = os.path.splitext(source)
    return source_base.replace(os.path.sep, '.')

  @property
  def entry_point(self):
    if self._entry_point:
      return self._entry_point
    elif self.payload.sources.source_paths:
      assert len(self.payload.sources.source_paths) == 1
      entry_source = list(self.sources_relative_to_source_root())[0]
      return self._translate_to_entry_point(entry_source)
    else:
      return None

  @property
  def pexinfo(self):
    info = PexInfo.default()
    for repo in self._repositories:
      info.add_repository(repo)
    for index in self._indices:
      info.add_index(index)
    info.zip_safe = self._zip_safe
    info.always_write_cache = self._always_write_cache
    info.inherit_path = self._inherit_path
    info.entry_point = self.entry_point
    info.ignore_errors = self._ignore_errors
    return info
