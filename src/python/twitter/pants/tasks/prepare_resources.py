# ==================================================================================================
# Copyright 2012 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================
from collections import defaultdict

import os
import shutil

from twitter.common.dirutil import safe_mkdir
from twitter.pants.goal.products import MultipleRootedProducts

from twitter.pants.tasks import Task


class PrepareResources(Task):

  def __init__(self, context):
    Task.__init__(self, context)

    self.workdir = context.config.get('prepare-resources', 'workdir')
    self.confs = context.config.getlist('prepare-resources', 'confs')
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
          target_resources.add_abs_paths(resources_dir, resources_tgt.sources)
