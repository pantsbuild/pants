# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import zipfile
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.task import Task
from pants.base.build_environment import get_buildroot
from pants.goal.products import MultipleRootedProducts
from pants.util.dirutil import relativize_path, safe_mkdir

class PrepareZippedResources(Task):
  """ This is a copy of pants.backend.core.tasks.prepare_resources.PrepareResources. The
  important differences being

  1) it produces a zip of the resources for this target, rather than a directory. This turns out
  to be a *lot* faster.
  2) only meant to be invoked for running jvm targets (junit, scala repl, and run.jvm).
  """

  @classmethod
  def product_types(cls):
    return ['zipped_resources_by_target']

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('compile_classpath')
    # NOTE(Garrett Malmquist): This is a fake dependency to force resources to occur after jvm
    # compile. It solves some problems we've been having getting our annotation processors to
    # compile consistently due to extraneous resources polluting the classpath. Perhaps this could
    # be fixed more elegantly whenever we get a formal classpath object?
    round_manager.require_data('classes_by_target')

  def __init__(self, *args, **kwargs):
    super(PrepareZippedResources, self).__init__(*args, **kwargs)
    self.confs = self.context.config.getlist('prepare-resources', 'confs', default=['default'])
    self._buildroot = get_buildroot()

  def execute(self):

    if self.context.products.is_required_data('zipped_resources_by_target'):
      self.context.products.safe_create_data('zipped_resources_by_target',
                                             lambda: defaultdict(MultipleRootedProducts))

    # `targets` contains the transitive subgraph in pre-order, which is approximately how
    # we want them ordered on the classpath. Thus, we preserve ordering here.
    targets = self.context.targets()
    if len(targets) == 0:
      return

    def extract_resources(target):
      return target.resources if target.has_resources else ()
    all_resources_tgts = OrderedSet()
    for resources_tgts in map(extract_resources, targets):
      all_resources_tgts.update(resources_tgts)

    def compute_target_zip(tgt):
      # Sources are all relative to their roots: relativize directories as well to
      # breaking filesystem limits.
      return relativize_path(os.path.join(self.workdir, tgt.id), self._buildroot) + u'.zip'

    with self.invalidated(all_resources_tgts) as invalidation_check:
      invalid_targets = set()
      for vt in invalidation_check.invalid_vts:
        invalid_targets.update(vt.targets)

      for resources_tgt in invalid_targets:
        target_zip = compute_target_zip(resources_tgt)
        safe_mkdir(os.path.dirname(target_zip))
        with zipfile.ZipFile(target_zip, 'w') as zipf:
          for resource_file_from_source_root in resources_tgt.sources_relative_to_source_root():
            zipf.write(os.path.join(resources_tgt.target_base, resource_file_from_source_root),
                       resource_file_from_source_root)

      resources_by_target = self.context.products.get_data('zipped_resources_by_target')
      compile_classpath = self.context.products.get_data('compile_classpath')

      for resources_tgt in all_resources_tgts:
        target_zip = compute_target_zip(resources_tgt)
        for conf in self.confs:
          # TODO(John Sirois): Introduce the notion of RuntimeClasspath and populate that product
          # instead of mutating the compile_classpath.
          compile_classpath.add_for_targets(targets, [(conf, target_zip)])
        if resources_by_target is not None:
          resources_by_target[resources_tgt].add_rel_paths(
            target_zip, resources_tgt.sources_relative_to_source_root())
