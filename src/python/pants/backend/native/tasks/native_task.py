# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import filter

from pants.backend.native.subsystems.native_build_settings import NativeBuildSettings
from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.external_native_library import ExternalNativeLibrary
from pants.backend.native.targets.native_library import NativeLibrary
from pants.build_graph.dependency_context import DependencyContext
from pants.task.task import Task
from pants.util.collections import assert_single_element
from pants.util.memo import memoized_classproperty, memoized_property
from pants.util.meta import classproperty
from pants.util.objects import SubclassesOf


class NativeTask(Task):

  @classproperty
  def source_target_constraint(cls):
    """Return a type constraint which is evaluated to determine "source" targets for this task.

    This is used to make it clearer which tasks act on which targets, since the compile and link
    tasks work on different target sets (just C and just C++ in the compile tasks, and both in the
    link task).

    :return: :class:`pants.util.objects.TypeConstraint`
    """
    raise NotImplementedError()

  @memoized_classproperty
  def dependent_target_constraint(cls):
    """Return a type contraint which is evaluated to determine dependencies for a target.

    This is used to make strict_deps() calculation automatic and declarative.

    :return: :class:`pants.util.objects.TypeConstraint`
    """
    return SubclassesOf(ExternalNativeLibrary, NativeLibrary)

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
