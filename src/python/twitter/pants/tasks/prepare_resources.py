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

__author__ = 'John Sirois'

import os
import shutil

from twitter.common.dirutil import safe_mkdir

from twitter.pants import has_resources
from twitter.pants.tasks import Task


class PrepareResources(Task):

  def __init__(self, context):
    Task.__init__(self, context)

    self.workdir = context.config.get('prepare-resources', 'workdir')
    self.confs = context.config.getlist('prepare-resources', 'confs')
    self.context.products.require_data('exclusives_groups')

  def execute(self, targets):
    def extract_resources(target):
      return target.resources if has_resources(target) else ()
    all_resources = set()
    for resources in map(extract_resources, targets):
      all_resources.update(resources)

    def target_dir(resources):
      return os.path.join(self.workdir, resources.id)

    with self.invalidated(all_resources) as invalidation_check:
      invalid_targets = set()
      for vt in invalidation_check.invalid_vts:
        invalid_targets.update(vt.targets)

      for resources in invalid_targets:
        resources_dir = target_dir(resources)
        safe_mkdir(resources_dir, clean=True)
        for resource in resources.sources:
          basedir = os.path.dirname(resource)
          destdir = os.path.join(resources_dir, basedir)
          safe_mkdir(destdir)
          shutil.copy(os.path.join(resources.target_base, resource),
                      os.path.join(resources_dir, resource))

    genmap = self.context.products.get('resources')
    egroups = self.context.products.get_data('exclusives_groups')
    group_key = egroups.get_group_key_for_target(targets[0])
    cp = egroups.get_classpath_for_group(group_key)
    for resources in all_resources:
      resources_dir = target_dir(resources)
      genmap.add(resources, resources_dir, resources.sources)
      for conf in self.confs:
        cp.insert(0, (conf, resources_dir))
