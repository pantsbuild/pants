# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.jvm_binary_task import JvmBinaryTask
from pants.build_graph.target_scopes import Scopes


class ConsolidateClasspath(JvmBinaryTask):
  """Convert loose directories in classpath_products into jars. """
  # Directory for both internal and external libraries.
  LIBS_DIR = 'libs'
  _target_closure_kwargs = dict(include_scopes=Scopes.JVM_RUNTIME_SCOPES, respect_intransitive=True)

  @classmethod
  def implementation_version(cls):
    return super(ConsolidateClasspath, cls).implementation_version() + [('ConsolidateClasspath', 1)]

  @classmethod
  def prepare(cls, options, round_manager):
    super(ConsolidateClasspath, cls).prepare(options, round_manager)
    round_manager.require_data('runtime_classpath')

  @property
  def cache_target_dirs(self):
    return True

  @classmethod
  def product_types(cls):
    return ['consolidated_classpath']

  def execute(self):
    # Clone the runtime_classpath to the consolidated_classpath.
    runtime_classpath = self.context.products.get_data('runtime_classpath')
    consolidated_classpath = self.context.products.get_data(
      'consolidated_classpath', runtime_classpath.copy)

    # TODO: use a smarter filter method we should be able to limit the targets a bit more.
    # https://github.com/pantsbuild/pants/issues/3807
    targets_to_consolidate = self.context.targets(**self._target_closure_kwargs)
    self._consolidate_classpath(targets_to_consolidate, consolidated_classpath)

  def _consolidate_classpath(self, targets, classpath_products):
    """Convert loose directories in classpath_products into jars. """
    # TODO: find a way to not process classpath entries for valid VTs.

    # NB: It is very expensive to call to get entries for each target one at a time.
    # For performance reasons we look them all up at once.
    entries_map = defaultdict(list)
    for (cp, target) in classpath_products.get_product_target_mappings_for_targets(targets, True):
      entries_map[target].append(cp)

    with self.invalidated(targets=targets, invalidate_dependents=True) as invalidation:
      for vt in invalidation.all_vts:
        entries = entries_map.get(vt.target, [])
        for index, (conf, entry) in enumerate(entries):
          if ClasspathUtil.is_dir(entry.path):
            jarpath = os.path.join(vt.results_dir, 'output-{}.jar'.format(index))

            # Regenerate artifact for invalid vts.
            if not vt.valid:
              with self.open_jar(jarpath, overwrite=True, compressed=False) as jar:
                jar.write(entry.path)

            # Replace directory classpath entry with its jarpath.
            classpath_products.remove_for_target(vt.target, [(conf, entry.path)])
            classpath_products.add_for_target(vt.target, [(conf, jarpath)])
