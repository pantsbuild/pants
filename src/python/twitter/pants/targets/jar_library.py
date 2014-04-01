# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from functools import partial

from twitter.common.collections import OrderedSet, maybe_list

from pants.base.build_manual import manual
from pants.base.target import Target, TargetDefinitionException
from pants.targets import util
from pants.targets.anonymous import AnonymousDeps
from pants.targets.exclude import Exclude
from pants.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.targets.external_dependency import ExternalDependency
from pants.targets.jar_dependency import JarDependency
from pants.targets.pants_target import Pants


@manual.builddict(tags=["anylang"])
class JarLibrary(Target):
  """A set of dependencies that may be depended upon,
  as if depending upon the set of dependencies directly.
  """

  def __init__(self, name, dependencies, overrides=None, exclusives=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :param overrides: List of strings, each of which will be recursively resolved to
      any targets that provide artifacts. Those artifacts will override corresponding
      direct/transitive dependencies in the dependencies list.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """
    super(JarLibrary, self).__init__(name, exclusives=exclusives)

    self._pre_override_dependencies = OrderedSet(
        maybe_list(util.resolve(dependencies),
                   expected_type=(ExternalDependency, AnonymousDeps, Target),
                   raise_type=partial(TargetDefinitionException, self)))
    self._dependencies = None
    self._dependency_addresses = None
    self.override_targets = set(map(Pants, overrides or []))
    self.add_labels('jars')

  @property
  def dependencies(self):
    if self._dependencies is None:
      # compute overridden dependencies
      self._dependencies = self._resolve_overrides()
    return self._dependencies

  @property
  def dependency_addresses(self):
    if self._dependency_addresses is None:
      self._dependency_addresses = set()
      for dependency in self.dependencies:
        if hasattr(dependency, 'address'):
          self._dependency_addresses.add(dependency.address)
        # If the dependency is one that supports exclusives, the JarLibrary's
        # exclusives should be added to it.
        if hasattr(dependency, 'declared_exclusives'):
          for k in self.declared_exclusives:
            dependency.declared_exclusives[k] |= self.declared_exclusives[k]
    return self._dependency_addresses

  def resolve(self):
    yield self
    for dependency in self.dependencies:
      for resolved_dependency in dependency.resolve():
        yield resolved_dependency

  def _resolve_overrides(self):
    """
    Resolves override targets, and then excludes and re-includes each of them
    to create and return a new dependency set.
    """
    if not self.override_targets:
      return self._pre_override_dependencies

    result = OrderedSet()

    # resolve overrides and fetch all of their "artifact-providing" dependencies
    excludes = set()
    for override_target in self.override_targets:
      # add pre_override deps of the target as exclusions
      for resolved in override_target.resolve():
        excludes.update(self._excludes(resolved))
      # prepend the target as a new target
      result.add(override_target)

    # add excludes for each artifact
    for direct_dep in self._pre_override_dependencies:
      # add relevant excludes to jar dependencies
      for jar_dep in self._jar_dependencies(direct_dep):
        for exclude in excludes:
          jar_dep.exclude(exclude.org, exclude.name)
      result.add(direct_dep)

    return result

  def _excludes(self, dep):
    """
    A generator for Exclude objects that will recursively exclude all artifacts
    provided by the given dep.
    """
    if isinstance(dep, JarDependency):
      yield Exclude(dep.org, dep.name)
    elif isinstance(dep, ExportableJvmLibrary):
      if not dep.provides:
        raise TargetDefinitionException(self,
            'Targets passed to `overrides` must represent published artifacts. %s does not.' % dep)
      yield Exclude(dep.provides.org, dep.provides.name)
    elif isinstance(dep, JarLibrary):
      for d in dep._pre_override_dependencies:
        for exclude in self._excludes(d):
          yield exclude

  def _jar_dependencies(self, dep):
    """
    A generator for JarDependencies transitively included by the given dep.
    """
    if isinstance(dep, JarDependency):
      yield dep
    elif isinstance(dep, JarLibrary):
      for direct_dep in dep._pre_override_dependencies:
        for dep in self._jar_dependencies(direct_dep):
          yield dep
    elif isinstance(dep, Pants):
      for d in self._jar_dependencies(dep.get()):
        yield d
