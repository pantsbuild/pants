# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.base.address import Address
from pants.base.exceptions import TargetDefinitionException


class ScalaLibrary(ExportableJvmLibrary):
  """A collection of Scala code.

  Normally has conceptually-related sources; invoking the ``compile`` goal
  on this target compiles scala and generates classes. Invoking the ``bundle``
  goal on this target creates a ``.jar``; but that's an unusual thing to do.
  Instead, a ``jvm_binary`` might depend on this library; that binary is a
  more sensible thing to bundle.
  """

  @classmethod
  def subsystems(cls):
    return super(ScalaLibrary, cls).subsystems() + (ScalaPlatform, )

  def __init__(self, java_sources=None, **kwargs):
    """
    :param java_sources: Java libraries this library has a *circular*
      dependency on.
      If you don't have the particular problem of circular dependencies
      forced by splitting interdependent java and scala into multiple targets,
      don't use this at all.
      Prefer using ``dependencies`` to express non-circular dependencies.
    :type java_sources: target spec or list of target specs
    :param resources: An optional list of paths (DEPRECATED) or ``resources``
      targets containing resources that belong on this library's classpath.
    """
    self._java_sources_specs = self.assert_list(java_sources, key_arg='java_sources')
    super(ScalaLibrary, self).__init__(**kwargs)
    self.add_labels('scala')

  @property
  def traversable_dependency_specs(self):
    for spec in super(ScalaLibrary, self).traversable_dependency_specs:
      yield spec

    # TODO(John Sirois): Targets should be able to set their scala platform version
    # explicitly, and not have to conform to this global setting.
    for library_spec in ScalaPlatform.global_instance().runtime:
      yield library_spec

  @property
  def traversable_specs(self):
    for spec in super(ScalaLibrary, self).traversable_specs:
      yield spec
    for java_source_spec in self._java_sources_specs:
      yield java_source_spec

  def get_jar_dependencies(self):
    for jar in super(ScalaLibrary, self).get_jar_dependencies():
      yield jar
    for java_source_target in self.java_sources:
      for jar in java_source_target.jar_dependencies:
        yield jar

  @property
  def java_sources(self):
    for spec in self._java_sources_specs:
      address = Address.parse(spec, relative_to=self.address.spec_path)
      target = self._build_graph.get_target(address)
      if target is None:
        raise TargetDefinitionException(self, 'No such java target: {}'.format(spec))
      yield target
