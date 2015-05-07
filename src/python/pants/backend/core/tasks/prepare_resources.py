# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import shutil
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.task import Task
from pants.base.build_environment import get_buildroot
from pants.goal.products import MultipleRootedProducts
from pants.option.options import Options
from pants.util.contextutil import open_zip
from pants.util.dirutil import relativize_path, safe_mkdir


class PrepareResources(Task):

  @classmethod
  def register_options(cls, register):
    super(PrepareResources, cls).register_options(register)
    register('--confs', advanced=True, type=Options.list, default=['default'],
             help='Prepare resources for these Ivy confs.')
    register('--resources-dir-patterns-for-jarring', advanced=True, type=Options.list, default=[],
             help='Specify regex patterns of resources directories that should be zipped into '
                  'jars.')
    register('--short-resources-jar-path', advanced=True, action='store_true', default=True,
             help='Replace the target id in a resource jar file path with a unique and randomized '
                  'id to shorten the file path.')

  @classmethod
  def product_types(cls):
    return ['resources_by_target']

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('compile_classpath')
    # NOTE(Garrett Malmquist): This is a fake dependency to force resources to occur after jvm
    # compile. It solves some problems we've been having getting our annotation processors to
    # compile consistently due to extraneous resources polluting the classpath. Perhaps this could
    # be fixed more elegantly whenever we get a formal classpath object?
    round_manager.require_data('classes_by_target')

  def __init__(self, *args, **kwargs):
    super(PrepareResources, self).__init__(*args, **kwargs)
    self._buildroot = get_buildroot()

    self.confs = self.get_options().confs

    self.patterns = []
    for pattern in self.get_options().resources_dir_patterns_for_jarring:
      self.patterns.append(re.compile(pattern))

    self.short_jar_path = self.get_options().short_resources_jar_path

    self.context.log.info(
      '================> patterns: {}'.format(list((r.pattern for r in self.patterns))))
    self.context.log.info(
      '================> short_path: {}'.format(self.short_jar_path))

  def execute(self):
    if self.context.products.is_required_data('resources_by_target'):
      self.context.products.safe_create_data('resources_by_target',
                                             lambda: defaultdict(MultipleRootedProducts))

    # NB: Ordering isn't relevant here, because it is applied during the dep walk to
    # consume from the compile_classpath.
    targets = self.context.targets()
    if len(targets) == 0:
      return
    def extract_resources(target):
      return target.resources if target.has_resources else ()
    all_resources_tgts = OrderedSet()
    for resources_tgts in map(extract_resources, targets):
      all_resources_tgts.update(resources_tgts)

    def compute_target_dir(tgt):
      # Sources are all relative to their roots: relativize directories as well to
      # breaking filesystem limits.
      return relativize_path(os.path.join(self.workdir, tgt.id), self._buildroot)

    def compute_target_jar(tgt):
      return relativize_path(os.path.join(self.workdir, tgt.id + '.jar'), self._buildroot)

    with self.invalidated(all_resources_tgts) as invalidation_check:
      invalid_targets = set()
      for vt in invalidation_check.invalid_vts:
        invalid_targets.update(vt.targets)

      for resources_tgt in invalid_targets:
        target_dir = compute_target_dir(resources_tgt)
        target_jar = compute_target_jar(resources_tgt)
        self.context.log.info('-----------> target_jar: {}'.format(target_jar))
#        safe_mkdir(target_dir, clean=True)
        safe_mkdir(os.path.dirname(target_jar))
        with open_zip(target_jar, 'w') as jar:
          for resource_file_from_source_root in resources_tgt.sources_relative_to_source_root():
            self.context.log.info(
              '---------------------> {}'.format(resource_file_from_source_root))
            jar.write(
              os.path.join(resources_tgt.target_base, resource_file_from_source_root),
              resource_file_from_source_root)
#            basedir = os.path.dirname(resource_file_from_source_root)
#            destdir = os.path.join(target_dir, basedir)
#            safe_mkdir(destdir)
            # TODO: Symlink instead?
#            shutil.copy(os.path.join(resources_tgt.target_base, resource_file_from_source_root),
#                        os.path.join(target_dir, resource_file_from_source_root))

      resources_by_target = self.context.products.get_data('resources_by_target')
      compile_classpath = self.context.products.get_data('compile_classpath')

      for resources_tgt in all_resources_tgts:
        target_dir = compute_target_dir(resources_tgt)
        target_jar = compute_target_jar(resources_tgt)
        for conf in self.confs:
          # TODO(John Sirois): Introduce the notion of RuntimeClasspath and populate that product
          # instead of mutating the compile_classpath.
          compile_classpath.add_for_target(resources_tgt, [(conf, target_jar)])
        if resources_by_target is not None:
          resources_by_target[resources_tgt].add_rel_paths(
            target_jar, resources_tgt.sources_relative_to_source_root())
