# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import filter

from pants.backend.native.subsystems.native_build_settings import NativeBuildSettings
from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.native_library import NativeLibrary
from pants.build_graph.dependency_context import DependencyContext
from pants.task.task import Task
from pants.util.collections import assert_single_element
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf


class NativeTask(Task):

  # `NativeCompile` will use the `source_target_constraint` to determine what targets have "sources"
  # to compile, and the `dependent_target_constraint` to determine which dependent targets to
  # operate on for `strict_deps` calculation.
  # NB: `source_target_constraint` must be overridden.
  source_target_constraint = None
  dependent_target_constraint = SubclassesOf(NativeLibrary)

  @classmethod
  def subsystem_dependencies(cls):
    return super(NativeTask, cls).subsystem_dependencies() + (
      NativeBuildSettings.scoped(cls),
      NativeToolchain.scoped(cls),
    )

  @classmethod
  def implementation_version(cls):
    return super(NativeTask, cls).implementation_version() + [('NativeTask', 0)]

  @memoized_property
  def _native_build_settings(self):
    return NativeBuildSettings.scoped_instance(self)

  @memoized_property
  def _native_toolchain(self):
    return NativeToolchain.scoped_instance(self)

  def native_deps(self, target):
    return self.strict_deps_for_target(
      target, predicate=self.dependent_target_constraint.satisfied_by)

  def strict_deps_for_target(self, target, predicate=None):
    """Get the dependencies of `target` filtered by `predicate`, accounting for 'strict_deps'.

    If 'strict_deps' is on, instead of using the transitive closure of dependencies, targets will
    only be able to see their immediate dependencies declared in the BUILD file. The 'strict_deps'
    setting is obtained from the result of `get_compile_settings()`.

    NB: This includes the current target in the result.
    """
    if self._native_build_settings.get_strict_deps_value_for_target(target):
      strict_deps = target.strict_dependencies(DependencyContext())
      if predicate:
        filtered_deps = list(filter(predicate, strict_deps))
      else:
        filtered_deps = strict_deps
      deps = [target] + filtered_deps
    else:
      deps = self.context.build_graph.transitive_subgraph_of_addresses(
        [target.address], predicate=predicate)

    return deps

  def _add_product_at_target_base(self, product_mapping, target, value):
    product_mapping.add(target, target.target_base).append(value)

  def _retrieve_single_product_at_target_base(self, product_mapping, target):
    self.context.log.debug("product_mapping: {}".format(product_mapping))
    self.context.log.debug("target: {}".format(target))
    product = product_mapping.get(target)
    single_base_dir = assert_single_element(product.keys())
    single_product = assert_single_element(product[single_base_dir])
    return single_product

  # TODO(#5869): delete this when we can request Subsystems from options in tasks!
  def _request_single(self, product, subject):
    # NB: This is not supposed to be exposed to Tasks yet -- see #4769 to track the status of
    # exposing v2 products in v1 tasks.
    return self.context._scheduler.product_request(product, [subject])[0]
