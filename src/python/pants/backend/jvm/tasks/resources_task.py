# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod

from pants.option.custom_types import list_option
from pants.task.task import Task


class ResourcesTask(Task):
  """A base class for tasks that process or create resource files.

  This base assumes that resources targets or targets that generate resources are independent from
  each other and can be processed in isolation in any order.
  """

  @classmethod
  def product_types(cls):
    return ['runtime_classpath']

  @classmethod
  def register_options(cls, register):
    super(ResourcesTask, cls).register_options(register)
    register('--confs', advanced=True, type=list_option, default=['default'],
             help='Prepare resources for these Ivy confs.')

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('compile_classpath')

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    # Tracked and returned for use in tests.
    # TODO: Rewrite those tests. execute() is not supposed to return anything.
    processed_targets = []

    compile_classpath = self.context.products.get_data('compile_classpath')
    runtime_classpath = self.context.products.get_data('runtime_classpath', compile_classpath.copy)

    all_relevant_resources_targets = self.find_all_relevant_resources_targets()
    if not all_relevant_resources_targets:
      return processed_targets

    with self.invalidated(targets=all_relevant_resources_targets,
                          fingerprint_strategy=self.create_invalidation_strategy(),
                          invalidate_dependents=False,
                          topological_order=False) as invalidation:
      for vt in invalidation.all_vts:
        # Register the target's chroot in the products.
        for conf in self.get_options().confs:
          runtime_classpath.add_for_target(vt.target, [(conf, vt.results_dir)])
        # And if it was invalid, generate the resources to the chroot.
        if not vt.valid:
          self.prepare_resources(vt.target, vt.results_dir)
          processed_targets.append(vt.target)
          vt.update()

    return processed_targets

  @abstractmethod
  def find_all_relevant_resources_targets(self):
    """Returns an iterable over all the relevant resources targets in the context."""

  def create_invalidation_strategy(self):
    """Creates a custom fingerprint strategy for determining invalid resources targets.

    :returns: A custom fingerprint strategy to use for determining invalid targets, or `None` to
              use the standard target payload.
    :rtype: :class:`pants.base.fingerprint_strategy.FingerprintStrategy`
    """
    return None

  @abstractmethod
  def prepare_resources(self, target, chroot):
    """Prepares the resources associated with `target` in the given `chroot`.

    :param target: The target to prepare resource files for.
    :type target: :class:`pants.build_graph.target.Target`
    :param string chroot: An existing, clean chroot dir to generate `target`'s resources to.
    """
