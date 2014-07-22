# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import os
import shutil

from pants.backend.core.tasks.task import Task
from pants.goal.products import MultipleRootedProducts
from pants.util.dirutil import safe_mkdir

class PrepareResources(Task):

  @classmethod
  def product_types(cls):
    return ['resources_by_target']

  def __init__(self, context, workdir):
    super(PrepareResources, self).__init__(context, workdir)
    self.confs = context.config.getlist('prepare-resources', 'confs', default=['default'])

  def prepare(self, round_manager):
    round_manager.require_data('exclusives_groups')
    # NOTE(Garrett Malmquist): This is a fake dependency to force resources to occur after jvm
    # compile. It solves some problems we've been having getting our annotation processors to
    # compile consistently due to extraneous resources polluting the classpath. Perhaps this could
    # be fixed more elegantly whenever we get a formal classpath object?
    round_manager.require_data('classes_by_target')

  def execute(self):
    if self.context.products.is_required_data('resources_by_target'):
      self.context.products.safe_create_data('resources_by_target',
                                             lambda: defaultdict(MultipleRootedProducts))

    targets = self.context.targets()
    if len(targets) == 0:
      return
    def extract_resources(target):
      return target.resources if target.has_resources else ()
    all_resources_tgts = set()
    for resources_tgts in map(extract_resources, targets):
      all_resources_tgts.update(resources_tgts)

    def compute_target_dir(tgt):
      return os.path.join(self.workdir, tgt.id)

    with self.invalidated(all_resources_tgts) as invalidation_check:
      invalid_targets = set()
      for vt in invalidation_check.invalid_vts:
        invalid_targets.update(vt.targets)

      for resources_tgt in invalid_targets:
        target_dir = compute_target_dir(resources_tgt)
        safe_mkdir(target_dir, clean=True)
        for resource_file_from_source_root in resources_tgt.sources_relative_to_source_root():
          basedir = os.path.dirname(resource_file_from_source_root)
          destdir = os.path.join(target_dir, basedir)
          safe_mkdir(destdir)
          # TODO: Symlink instead?
          shutil.copy(os.path.join(resources_tgt.target_base, resource_file_from_source_root),
                      os.path.join(target_dir, resource_file_from_source_root))

      resources_by_target = self.context.products.get_data('resources_by_target')
      egroups = self.context.products.get_data('exclusives_groups')
      group_key = egroups.get_group_key_for_target(targets[0])

      for resources_tgt in all_resources_tgts:
        target_dir = compute_target_dir(resources_tgt)
        for conf in self.confs:
          # TODO(John Sirois): Introduce the notion of RuntimeClasspath and populate that product
          # instead of mutating exclusives_groups.
          egroups.update_compatible_classpaths(group_key, [(conf, target_dir)])
        if resources_by_target is not None:
          resources_by_target[resources_tgt].add_rel_paths(
            target_dir, resources_tgt.sources_relative_to_source_root())
