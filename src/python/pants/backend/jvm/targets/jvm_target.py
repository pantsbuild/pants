# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.lang import Compatibility

from pants.base.address import SyntheticAddress
from pants.base.payload import JvmTargetPayload
from pants.base.target import Target
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jarable import Jarable


class JvmTarget(Target, Jarable):
  """A base class for all java module targets that provides path and dependency translation."""

  def __init__(self,
               address=None,
               sources=None,
               sources_rel_path=None,
               provides=None,
               excludes=None,
               resources=None,
               configurations=None,
               **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param excludes: One or more :class:`pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param configurations: One or more ivy configurations to resolve for this target.
      This parameter is not intended for general use.
    :type configurations: tuple of strings
    """

    sources_rel_path = sources_rel_path or address.spec_path
    payload = JvmTargetPayload(sources=sources,
                               sources_rel_path=sources_rel_path,
                               provides=provides,
                               excludes=excludes,
                               configurations=configurations)
    super(JvmTarget, self).__init__(address=address, payload=payload, **kwargs)

    self._resource_specs = resources or []
    self.add_labels('jvm')

  _jar_dependencies = None
  @property
  def jar_dependencies(self):
    if self._jar_dependencies is None:
      self._jar_dependencies = set(self.get_jar_dependencies())
    return self._jar_dependencies

  def mark_extra_invalidation_hash_dirty(self):
    self._jar_dependencies = None

  def get_jar_dependencies(self):
    jar_deps = set()
    def collect_jar_deps(target):
      if isinstance(target, JarLibrary):
        jar_deps.update(target.payload.jars)

    self.walk(work=collect_jar_deps)
    return jar_deps

  @property
  def has_resources(self):
    return len(self.resources) > 0

  @property
  def traversable_dependency_specs(self):
    for spec in super(JvmTarget, self).traversable_specs:
      yield spec
    for resource_spec in self._resource_specs:
      yield resource_spec

  @property
  def traversable_specs(self):
    if self.payload.provides:
      yield self.payload.provides.repo

  @property
  def provides(self):
    if not self.payload.provides:
      return None

    # TODO(pl): This is an awful hack
    if isinstance(self.payload.provides.repo, Compatibility.string):
      address = SyntheticAddress.parse(self.payload.provides.repo,
                                       relative_to=self.address.spec_path)
      repo_target = self._build_graph.get_target(address)
      self.payload.provides.repo = repo_target
    return self.payload.provides

  @property
  def resources(self):
    return [self._build_graph.get_target_from_spec(spec) for spec in self._resource_specs]
