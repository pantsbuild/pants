# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.native_library import NativeLibrary
from pants.build_graph.dependency_context import DependencyContext
from pants.task.task import Task
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf


class NativeTask(Task):

  native_target_constraint = SubclassesOf(NativeLibrary)

  @classmethod
  def subsystem_dependencies(cls):
    return super(NativeTask, cls).subsystem_dependencies() + (NativeToolchain.scoped(cls),)

  @classmethod
  def register_options(cls, register):
    super(NativeTask, cls).register_options(register)

    register('--strict-deps', type=bool, default=True, fingerprint=True, advanced=True,
             help='???/The default for the "strict_deps" argument for targets of this language.')

  @memoized_property
  def _toolchain(self):
    return NativeToolchain.scoped_instance(self)

  def _request_single(self, product, subject):
    # FIXME(cosmicexplorer): This is not supposed to be exposed to Tasks yet -- see #4769 to track
    # the status of exposing v2 products in v1 tasks.
    return self.context._scheduler.product_request(product, [subject])[0]

  def get_task_target_field_value(self, field_name, target):
    """???/for fields with the same name on targets and tasks"""
    tgt_setting = getattr(target, field_name)
    if tgt_setting is None:
      return getattr(self.get_options(), field_name)
    return tgt_setting

  def native_deps(self, target):
    return self.strict_deps_for_target(target, predicate=self.native_target_constraint.satisfied_by)

  def strict_deps_for_target(self, target, predicate=None):
    """???/figure out strict deps and stuff

    This includes the current target in the result.
    """
    # TODO: note that the target's gotta have a strict_deps prop
    if self.get_task_target_field_value('strict_deps', target):
      # FIXME: does this include the current target? it almost definitely should (should it
      # though???) this actually isn't clear
      strict_deps = target.strict_dependencies(DependencyContext())
      if predicate:
        filtered_deps = filter(predicate, strict_deps)
      else:
        filtered_deps = strict_deps
      deps = [target] + filtered_deps
    else:
      deps = self.context.build_graph.transitive_subgraph_of_addresses([target.address],
                                                                       predicate=predicate)

    return deps
