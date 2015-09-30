# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import abstractmethod
from collections import defaultdict

from pants.backend.core.tasks.task import Task
from pants.base.build_environment import get_buildroot
from pants.goal.products import MultipleRootedProducts
from pants.option.custom_types import list_option
from pants.util.dirutil import relativize_path, safe_mkdir


class ResourcesTask(Task):
  """A base class for tasks that process or create resource files.

  This base assumes that resources targets or targets that generate resources are independent from
  each other and can be processed in isolation in any order.
  """

  @classmethod
  def product_types(cls):
    return ['resources_by_target']

  @classmethod
  def register_options(cls, register):
    super(ResourcesTask, cls).register_options(register)
    register('--confs', advanced=True, type=list_option, default=['default'],
             help='Prepare resources for these Ivy confs.')

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('compile_classpath')

  def compute_target_dir(self, target):
    # Sources are all relative to their roots: relativize directories as well to avoid
    # breaking filesystem path length limits.
    return relativize_path(os.path.join(self.workdir, target.id), get_buildroot())

  def execute(self):
    # Tracked and returned for use in tests.
    processed_targets = []

    self.context.products.safe_create_data('resources_by_target',
                                           lambda: defaultdict(MultipleRootedProducts))

    all_relevant_resources_targets = self.find_all_relevant_resources_targets()
    if not all_relevant_resources_targets:
      return processed_targets

    with self.invalidated(targets=all_relevant_resources_targets,
                          fingerprint_strategy=self.create_invalidation_strategy(),
                          invalidate_dependents=False,
                          topological_order=False) as invalidation:
      if invalidation.invalid_vts:
        for vts in invalidation.invalid_vts:
          for invalid_target in vts.targets:
            chroot = self.compute_target_dir(invalid_target)
            safe_mkdir(chroot, clean=True)
            self.prepare_resources(invalid_target, chroot)
            processed_targets.append(invalid_target)
          vts.update()

    resources_by_target = self.context.products.get_data('resources_by_target')
    compile_classpath = self.context.products.get_data('compile_classpath')
    for resources_target in all_relevant_resources_targets:
      chroot = self.compute_target_dir(resources_target)
      relative_resource_paths = self.relative_resource_paths(resources_target, chroot)
      if relative_resource_paths:
        for conf in self.get_options().confs:
          # TODO(John Sirois): Introduce the notion of RuntimeClasspath and populate that product
          # instead of mutating the compile_classpath.
          compile_classpath.add_for_target(resources_target, [(conf, chroot)])
        resources_by_target[resources_target].add_rel_paths(chroot, relative_resource_paths)

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

  def relative_resource_paths(self, target, chroot):
    """Returns the relative paths of the resource files this task prepares for `target`.

    The `chroot` is the same chroot passed to `prepare_resources` for this `target` and by default
    all files found in the chroot are returned.  Subclasses should override if there is a more
    efficient way to enumerate the resource files than a filesystem walk of the chroot.

    :param target: The target to calculate relative resource paths for.
    :type target: :class:`pants.build_graph.target.Target`
    :param string chroot: The chroot path that `target`'s resources have been generated to.
    :returns: A list of relative paths.
    """
    def iter_paths():
      for root, dirs, files in os.walk(chroot):
        for f in files:
          yield os.path.relpath(os.path.join(root, f), chroot)
    return list(iter_paths())
