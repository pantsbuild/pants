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
from pants.util.dirutil import safe_mkdir


class PrepareResources(ResourcesTask):
  """Prepares loose resource files associated with a target.

  Currently this task does no form of resource filtering, it just copies resource files to
  dedicated, isolated resource chroots for use in the classpath as well as for packaging purposes.
  """

  @classmethod
  def prepare(cls, options, round_manager):
    super(ResourcesTask, cls).prepare(options, round_manager)

    # NOTE(Garrett Malmquist): This is a fake dependency to force resources to occur after jvm
    # compile. It solves some problems we've been having getting our annotation processors to
    # compile consistently due to extraneous resources polluting the classpath. Perhaps this could
    # be fixed more elegantly whenever we get a formal classpath object?

    # TODO(John Sirois): Although we don't have a formal classpath object, we do have a compilation
    # mode that uses isolated classpaths and in that mode the Square problem should go away.
    # Kill this fake dep when Square is using the isolated compile strategy (or when pants is
    # globally).  Tracked by https://github.com/pantsbuild/pants/issues/1645

    round_manager.require_data('classes_by_target')

  def __init__(self, *args, **kwargs):
    super(PrepareResources, self).__init__(*args, **kwargs)
    self._buildroot = get_buildroot()

  def find_all_relevant_resources_targets(self):
    # NB: Ordering isn't relevant here, because it is applied during the dep walk to
    # consume from the compile_classpath.
    def is_jvm_target(target):
      return isinstance(target, JvmTarget)
    jvm_targets = self.context.targets(predicate=is_jvm_target)

    all_resources_tgts = OrderedSet()
    for target in jvm_targets:
      if target.has_resources:
        all_resources_tgts.update(target.resources)
    return all_resources_tgts

  def prepare_resources(self, target, chroot):
    for resource_file_from_source_root in target.sources_relative_to_source_root():
      basedir = os.path.dirname(resource_file_from_source_root)
      destdir = os.path.join(chroot, basedir)
      safe_mkdir(destdir)

      # TODO(Benjy Weinberger): Symlink instead?
      shutil.copy(os.path.join(self._buildroot, target.target_base, resource_file_from_source_root),
                  os.path.join(chroot, resource_file_from_source_root))

  def relative_resource_paths(self, target, chroot):
    return list(target.sources_relative_to_source_root())
