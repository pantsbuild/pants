# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.scala.target_platform import TargetPlatform
from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.base.address import SyntheticAddress
from pants.base.exceptions import TargetDefinitionException
from pants.base.validation import assert_list


class ScalaLibrary(ExportableJvmLibrary):
  """A collection of Scala code.

  Normally has conceptually-related sources; invoking the ``compile`` goal
  on this target compiles scala and generates classes. Invoking the ``bundle``
  goal on this target creates a ``.jar``; but that's an unusual thing to do.
  Instead, a ``jvm_binary`` might depend on this library; that binary is a
  more sensible thing to bundle.
  """

  def __init__(self, java_sources=None, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param java_sources: Java libraries this library has a *circular*
      dependency on.
      If you don't have the particular problem of circular dependencies
      forced by splitting interdependent java and scala into multiple targets,
      don't use this at all.
      Prefer using ``dependencies`` to express non-circular dependencies.
    :type java_sources: target spec or list of target specs
    :param provides: The ``artifact``
      to publish that represents this target outside the repo.
    :param dependencies: Other targets that this target depends on. If your
       code ``import``\s code from other places, it depends on them.
    :type dependencies: list of target specs
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param resources: An optional list of paths (DEPRECATED) or ``resources``
      targets containing resources that belong on this library's classpath.
    :param exclusives: An optional list of exclusives tags.
    """
    self._java_sources_specs = self.assert_list(java_sources)
    super(ScalaLibrary, self).__init__(**kwargs)
    self.add_labels('scala')

  @property
  def traversable_dependency_specs(self):
    for spec in super(ScalaLibrary, self).traversable_dependency_specs:
      yield spec

    # TODO(John Sirois): Targets should have a config plumbed as part of the implicit
    # BuildFileParser injected context and that could be used to allow in general for targets with
    # knobs and in particular an explict config arg to the TargetPlatform constructor below.
    for library_spec in TargetPlatform().library_specs:
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
      address = SyntheticAddress.parse(spec, relative_to=self.address.spec_path)
      target = self._build_graph.get_target(address)
      if target is None:
        raise TargetDefinitionException(self, 'No such java target: %s' % spec)
      yield target

  def closure(self):
    # Overrides the default implementation to return java_sources as well
    target_set = super(ScalaLibrary, self).closure()
    for java_source_target in self.java_sources:
      target_set.update(java_source_target.closure())
    return target_set
