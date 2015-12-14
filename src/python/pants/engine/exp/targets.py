# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os

from pants.backend.core.wrapped_globs import Globs, RGlobs, ZGlobs
from pants.engine.exp.addressable import Exactly, SubclassesOf, addressable, addressable_list
from pants.engine.exp.configuration import Configuration


class Sources(Configuration):
  """Represents a collection of source files."""

  def __init__(self,
               name=None,
               files=None,
               globs=None,
               rglobs=None,
               zglobs=None,
               excludes=None,
               **kwargs):
    """
    :param string name: An optional name of this set of sources if the set is top-level for sharing.
    :param files: A list of relative file paths to include.
    :type files: list of string.
    :param string globs: A relative glob pattern of files to include.
    :param string rglobs: A relative recursive glob pattern of files to include.
    :param string zglobs: A relative zsh-style glob pattern of files to include.
    :param zglobs: A relative zsh-style glob pattern of files to include.
    :param excludes: A set of sources to exclude from the sources gathered via files, globs, rglobs
                     and zglobs.
    :type excludes: :class:`Sources`
    """
    super(Sources, self).__init__(name=name, files=files, globs=globs, rglobs=rglobs, zglobs=zglobs,
                                  **kwargs)
    self.excludes = excludes

  @property
  def excludes(self):
    """The sources to exclude.

    :rtype: :class:`Sources`
    """

  def iter_paths(self, base_path=None, ext=None):
    """Return an iterator over this collection of sources file paths.

    If these sources are addressable, the paths returned will have a base path of the address
    `spec_path`; otherwise a `base_path` must be explicitly supplied.

    :param string base_path: If this collection of sources is not addressed, the base path in the
                             repo the sources are relative to.
    :param string ext: An optional file extension filter to restrict returned file paths with.
    :returns: An iterator over the source paths that match the given file extension (if any) and are
              not excluded by `excludes`.  Paths are of the form
              `os.path.join(base_path, rel_path)`.
    :rtype: :class:`collections.Iterator` of string
    """
    base_path = self.address.spec_path if self.address else base_path
    if not base_path:
      raise ValueError('A `base_path` must be supplied to iterate paths for {!r}'.format(self))

    def select(file_name):
      return file_name.endswith(ext) if ext else True

    excluded_files = frozenset(self.excludes.iter_paths(base_path)) if self.excludes else ()

    def file_sources():
      if self.files:
        yield self.files
      for spec, fileset_wrapper_type in ((self.globs, Globs),
                                         (self.rglobs, RGlobs),
                                         (self.zglobs, ZGlobs)):
        if spec:
          fileset = fileset_wrapper_type(base_path)(spec)
          yield fileset

    for rel_path in itertools.chain.from_iterable(file_sources()):
      if select(rel_path):
        file_path = os.path.join(base_path, rel_path)
        if file_path not in excluded_files:
          yield file_path

# Since Sources.excludes is recursive on the Sources type, we need to post-class-definition
# re-define excludes in this way.
Sources.excludes = addressable(Exactly(Sources))(Sources.excludes)


class Target(Configuration):
  """TODO(John Sirois): XXX DOCME"""

  class ConfigurationNotFound(Exception):
    """Indicates a requested configuration of a target could not be found."""

  def __init__(self, name=None, sources=None, configurations=None, dependencies=None, **kwargs):
    """
    :param string name: The name of this target which forms its address in its namespace.
    :param sources: The relative source file paths of sources this target owns.
    :type sources: :class:`Sources`
    :param list configurations: The configurations that apply to this target in various contexts.
    :param list dependencies: The direct dependencies of this target.
    """
    super(Target, self).__init__(name=name, **kwargs)
    self.configurations = configurations
    self.dependencies = dependencies
    self.sources = sources

  @addressable_list(SubclassesOf(Configuration))
  def configurations(self):
    """The configurations that apply to this target in various contexts.

    :rtype list of :class:`pants.engine.exp.configuration.Configuration`
    """

  @addressable_list(SubclassesOf(Configuration))
  def dependencies(self):
    """The direct dependencies of this target.

    :rtype: list
    """

  @addressable(Exactly(Sources))
  def sources(self):
    """Return the sources this target owns.

    :rtype: :class:`Sources`
    """

  def select_configuration(self, name):
    """Selects a named configuration of this target.

    :param string name: The name of the configuration to select.
    :returns: The configuration with the given name.
    :rtype: :class:`pants.engine.exp.configuration.Configuration`
    :raises: :class:`Target.ConfigurationNotFound` if the configuration was not found.
    """
    configs = tuple(config for config in self.configurations if config.name == name)
    if len(configs) != 1:
      configurations = ('{} -> {!r}'.format(repr(c.name) if c.name else '<anonymous>', c)
                        for c in configs)
      raise self.ConfigurationNotFound('Failed to find a single configuration named {!r} these '
                                       'configurations in {!r}:\n\t{}'
                                       .format(name, self, '\n\t'.join(configurations)))
    return configs[0]

  def walk_targets(self, postorder=True):
    """Performs a depth first walk of this target, visiting all reachable targets exactly once.

    :param bool postorder: When ``True``, the traversal order is postorder (children before
                           parents), else it is preorder (parents before children).
    """
    visited = set()

    def walk(target):
      if target not in visited:
        visited.add(target)
        if not postorder:
          yield target
        for dep in self.dependencies:
          if isinstance(dep, Target):
            for t in walk(dep):
              yield t
        if postorder:
          yield target

    for target in walk(self):
      yield target
