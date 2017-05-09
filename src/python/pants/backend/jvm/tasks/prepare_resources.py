# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.resources_task import ResourcesTask
from pants.base.build_environment import get_buildroot
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.util.dirutil import safe_mkdir


class PrepareResources(ResourcesTask):
  """Prepares loose resource files associated with a target.

  Currently this task does no form of resource filtering, it just copies resource files to
  dedicated, isolated resource chroots for use in the classpath as well as for packaging purposes.
  """

  def __init__(self, *args, **kwargs):
    super(PrepareResources, self).__init__(*args, **kwargs)
    self._buildroot = get_buildroot()

  @classmethod
  def implementation_version(cls):
    return super(PrepareResources, cls).implementation_version() + [('PrepareResources', 2)]

  def find_all_relevant_resources_targets(self):
    # NB: Ordering isn't relevant here, because it is applied during the dep walk to
    # consume from the runtime_classpath.
    def is_jvm_target(target):
      return isinstance(target, JvmTarget)
    jvm_targets = self.context.targets(predicate=is_jvm_target)

    all_resources_tgts = OrderedSet()
    for target in Target.closure_for_targets(jvm_targets, bfs=True):
      if isinstance(target, Resources):
        all_resources_tgts.add(target)
    return all_resources_tgts

  def prepare_resources(self, target, chroot):
    for resource_file_from_source_root in target.sources_relative_to_source_root():
      basedir = os.path.dirname(resource_file_from_source_root)
      destdir = os.path.join(chroot, basedir)
      safe_mkdir(destdir)

      # TODO(Benjy Weinberger): Symlink instead?
      shutil.copy(os.path.join(self._buildroot, target.target_base, resource_file_from_source_root),
                  os.path.join(chroot, resource_file_from_source_root))
