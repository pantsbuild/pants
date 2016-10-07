# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.intermediate_target_factory import IntermediateTargetFactoryBase


class IntransitiveDependencyFactory(IntermediateTargetFactoryBase):
  """Creates a dependency which is intransitive.

  This dependency will not be seen by dependees of this target. The syntax for this feature is
  experimental and may change in the future.
  """

  @property
  def extra_target_arguments(self):
    return dict(_transitive=False)

  def __call__(self, address):
    return self._create_intermediate_target(address, 'intransitive')


class ProvidedDependencyFactory(IntermediateTargetFactoryBase):
  """Creates an intransitive dependency with scope='compile test'.

  This mirrors the behavior of the "provided" scope found in other build systems, such as Gradle,
  Maven, and IntelliJ.

  The syntax for this feature is experimental and may change in the future.
  """

  @property
  def extra_target_arguments(self):
    return dict(_transitive=False, scope='compile test')

  def __call__(self, address):
    return self._create_intermediate_target(address, 'provided')
