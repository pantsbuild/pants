# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.address import Address


class ScalaLibrary(ExportableJvmLibrary):
  """A Scala library.

  Normally has conceptually-related sources; invoking the ``compile`` goal
  on this target compiles scala and generates classes. Invoking the ``bundle``
  goal on this target creates a ``.jar``; but that's an unusual thing to do.
  Instead, a ``jvm_binary`` might depend on this library; that binary is a
  more sensible thing to bundle.

  :API: public
  """

  default_sources_globs = '*.scala'
  default_sources_exclude_globs = JUnitTests.scala_test_globs

  @classmethod
  def subsystems(cls):
    return super(ScalaLibrary, cls).subsystems() + (ScalaPlatform, )

  def __init__(self, java_sources=None, payload=None, **kwargs):
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
    payload = payload or Payload()
    payload.add_fields({
      'java_sources': PrimitiveField(self.assert_list(java_sources, key_arg='java_sources')),
    })
    super(ScalaLibrary, self).__init__(payload=payload, **kwargs)
    self.add_labels('scala')

  @classmethod
  def compute_injectable_specs(cls, kwargs=None, payload=None):
    for spec in super(ScalaLibrary, cls).compute_injectable_specs(kwargs, payload):
      yield spec

    target_representation = kwargs or payload.as_dict()
    java_sources_specs = target_representation.get('java_sources', None) or []
    for java_source_spec in java_sources_specs:
      yield java_source_spec

  @classmethod
  def compute_dependency_specs(cls, kwargs=None, payload=None):
    for spec in super(ScalaLibrary, cls).compute_dependency_specs(kwargs, payload):
      yield spec

    for spec in ScalaPlatform.global_instance().injectables_specs_for_key('scala-library'):
      yield spec

  def get_jar_dependencies(self):
    for jar in super(ScalaLibrary, self).get_jar_dependencies():
      yield jar
    for java_source_target in self.java_sources:
      for jar in java_source_target.jar_dependencies:
        yield jar

  @property
  def java_sources(self):
    for spec in self.payload.java_sources:
      address = Address.parse(spec, relative_to=self.address.spec_path)
      target = self._build_graph.get_target(address)
      if target is None:
        raise TargetDefinitionException(self, 'No such java target: {}'.format(spec))
      yield target
