# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.lang import Compatibility

from pants.backend.core.targets.resources import Resources
from pants.backend.jvm.targets.exclude import Exclude
from pants.base.address import SyntheticAddress
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import JvmTargetPayload
from pants.base.target import Target
from pants.base.validation import assert_list
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
      build file defines the :doc:`target address <target_addresses>`.
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param configurations: One or more ivy configurations to resolve for this target.
      This parameter is not intended for general use.
    :type configurations: tuple of strings
    """

    sources_rel_path = sources_rel_path or address.spec_path
    payload = JvmTargetPayload(sources=self.assert_list(sources),
                               sources_rel_path=sources_rel_path,
                               provides=provides,
                               excludes=self.assert_list(excludes, expected_type=Exclude),
                               configurations=self.assert_list(configurations))
    super(JvmTarget, self).__init__(address=address, payload=payload, **kwargs)

    self._resource_specs = self.assert_list(resources)
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
      repo_spec = self.payload.provides.repo
      address = SyntheticAddress.parse(repo_spec, relative_to=self.address.spec_path)
      repo_target = self._build_graph.get_target(address)
      if repo_target is None:
        raise TargetDefinitionException(self, 'No such repo target: %s' % repo_spec)
      self.payload.provides.repo = repo_target
    return self.payload.provides

  @property
  def resources(self):
    # TODO(John Sirois): Consider removing this convenience:
    #   https://github.com/pantsbuild/pants/issues/346
    # TODO(John Sirois): Introduce a label and replace the type test?
    return [dependency for dependency in self.dependencies if isinstance(dependency, Resources)]

  @property
  def excludes(self):
    return self.payload.excludes
