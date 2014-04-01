# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import shutil
from collections import defaultdict

from twitter.common.dirutil import safe_mkdir

from pants.goal.products import MultipleRootedProducts
from pants.tasks import Task


class PrepareResources(Task):

  def __init__(self, context):
    Task.__init__(self, context)

    self.workdir = context.config.get('prepare-resources', 'workdir')
    self.confs = context.config.getlist('prepare-resources', 'confs', default=['default'])
    self.context.products.require_data('exclusives_groups')

  def execute(self, targets):
    if self.context.products.is_required_data('resources_by_target'):
      self.context.products.safe_create_data('resources_by_target',
                                             lambda: defaultdict(MultipleRootedProducts))

    if len(targets) == 0:
      return
    def extract_resources(target):
      return target.resources if target.has_resources else ()
    all_resources_tgts = set()
    for resources_tgts in map(extract_resources, targets):
      all_resources_tgts.update(resources_tgts)

    def target_dir(resources_tgt):
      return os.path.join(self.workdir, resources_tgt.id)

    with self.invalidated(all_resources_tgts) as invalidation_check:
      invalid_targets = set()
      for vt in invalidation_check.invalid_vts:
        invalid_targets.update(vt.targets)

      for resources_tgt in invalid_targets:
        resources_dir = target_dir(resources_tgt)
        safe_mkdir(resources_dir, clean=True)
        for resource_path in resources_tgt.sources:
          basedir = os.path.dirname(resource_path)
          destdir = os.path.join(resources_dir, basedir)
          safe_mkdir(destdir)
          # TODO: Symlink instead?
          shutil.copy(os.path.join(resources_tgt.target_base, resource_path),
                      os.path.join(resources_dir, resource_path))

      resources_by_target = self.context.products.get_data('resources_by_target')
      egroups = self.context.products.get_data('exclusives_groups')
      group_key = egroups.get_group_key_for_target(targets[0])

      for resources_tgt in all_resources_tgts:
        resources_dir = target_dir(resources_tgt)
        for conf in self.confs:
          egroups.update_compatible_classpaths(group_key, [(conf, resources_dir)])
        if resources_by_target is not None:
          target_resources = resources_by_target[resources_tgt]
          target_resources.add_rel_paths(resources_dir, resources_tgt.sources)
