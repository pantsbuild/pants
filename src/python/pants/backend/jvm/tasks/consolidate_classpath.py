# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.jvm_binary_task import JvmBinaryTask
from pants.build_graph.target_scopes import Scopes


class ConsolidatedClasspath(JvmBinaryTask):
  # Directory for both internal and external libraries.
  LIBS_DIR = 'libs'
  _target_closure_kwargs = dict(include_scopes=Scopes.JVM_RUNTIME_SCOPES, respect_intransitive=True)

  @classmethod
  def implementation_version(cls):
    return super(ConsolidatedClasspath, cls).implementation_version() + [('ConsolidatedClasspath', 1)]

  @classmethod
  def prepare(cls, options, round_manager):
    super(ConsolidatedClasspath, cls).prepare(options, round_manager)
    round_manager.require_data('runtime_classpath')

  @property
  def cache_target_dirs(self):
    return True

  @classmethod
  def product_types(cls):
    return ['consolidated_classpath']

  def execute(self):
    # NB(peiyu): performance hack to convert loose directories in classpath into jars. This is
    # more efficient than loading them as individual files.

    # Clone the runtime_classpath to the consolidated_classpath.
    runtime_classpath = self.context.products.get_data('runtime_classpath')
    consolidated_classpath = self.context.products.get_data(
      'consolidated_classpath', runtime_classpath.copy)

    targets_to_consolidate = self.find_consolidate_classpath_candidates(
      consolidated_classpath,
      self.context.targets(**self._target_closure_kwargs),
    )
    self.consolidate_classpath(targets_to_consolidate, consolidated_classpath)

  def consolidate_classpath(self, targets, classpath_products):
    """Convert loose directories in classpath_products into jars. """
    with self.invalidated(targets=targets, invalidate_dependents=True) as invalidation:
      for vt in invalidation.all_vts:
        entries = classpath_products.get_internal_classpath_entries_for_targets([vt.target])
        for index, (conf, entry) in enumerate(entries):
          if ClasspathUtil.is_dir(entry.path):
            jarpath = os.path.join(vt.results_dir, 'output-{}.jar'.format(index))

            # regenerate artifact for invalid vts
            if not vt.valid:
              with self.open_jar(jarpath, overwrite=True, compressed=False) as jar:
                jar.write(entry.path)

            # replace directory classpath entry with its jarpath
            classpath_products.remove_for_target(vt.target, [(conf, entry.path)])
            classpath_products.add_for_target(vt.target, [(conf, jarpath)])

  def find_consolidate_classpath_candidates(self, classpath_products, targets):
    targets_with_directory_in_classpath = []
    for target in targets:
      entries = classpath_products.get_internal_classpath_entries_for_targets([target])
      for conf, entry in entries:
        if ClasspathUtil.is_dir(entry.path):
          targets_with_directory_in_classpath.append(target)
          break

    return targets_with_directory_in_classpath
