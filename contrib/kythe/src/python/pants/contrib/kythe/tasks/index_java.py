# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel

from pants.contrib.kythe.tasks.indexable_java_targets import IndexableJavaTargets


class IndexJava(NailgunTask):
  cache_target_dirs = True

  _KYTHE_INDEXER_MAIN = 'com.google.devtools.kythe.analyzers.java.JavaIndexer'

  @classmethod
  def subsystem_dependencies(cls):
    return super(IndexJava, cls).subsystem_dependencies() + (IndexableJavaTargets,)

  @classmethod
  def implementation_version(cls):
    # Bump this version to invalidate all past artifacts generated by this task.
    return super(IndexJava, cls).implementation_version() + [('IndexJava', 7), ]

  @classmethod
  def product_types(cls):
    return ['kythe_entries_files']

  @classmethod
  def prepare(cls, options, round_manager):
    super(IndexJava, cls).prepare(options, round_manager)
    round_manager.require_data('kindex_files')

  @classmethod
  def register_options(cls, register):
    super(IndexJava, cls).register_options(register)
    cls.register_jvm_tool(register,
                          'kythe-indexer',
                          main=cls._KYTHE_INDEXER_MAIN)

  def execute(self):
    def entries_file(_vt):
      return os.path.join(_vt.results_dir, 'index.entries')

    indexable_targets = IndexableJavaTargets.global_instance().get(self.context)

    with self.invalidated(indexable_targets, invalidate_dependents=True) as invalidation_check:
      kindex_files = self.context.products.get_data('kindex_files')

      indexer_cp = self.tool_classpath('kythe-indexer')
      # Kythe jars embed a copy of Java 9's com.sun.tools.javac and javax.tools, for use on JDK8.
      # We must put these jars on the bootclasspath, ahead of any others, to ensure that we load
      # the Java 9 versions, and not the runtime's versions.
      jvm_options = ['-Xbootclasspath/p:{}'.format(':'.join(indexer_cp))]
      jvm_options.extend(self.get_options().jvm_options)

      for vt in invalidation_check.invalid_vts:
        self.context.log.info('Kythe indexing {}'.format(vt.target.address.spec))
        kindex_file = kindex_files.get(vt.target)
        if not kindex_file:
          raise TaskError('No .kindex file found for {}'.format(vt.target.address.spec))
        args = [kindex_file, '--out', entries_file(vt)]
        result = self.runjava(classpath=indexer_cp, main=self._KYTHE_INDEXER_MAIN,
                              jvm_options=jvm_options,
                              args=args, workunit_name='kythe-index',
                              workunit_labels=[WorkUnitLabel.COMPILER])
        if result != 0:
          raise TaskError('java {main} ... exited non-zero ({result})'.format(
            main=self._KYTHE_INDEXER_MAIN, result=result))

    for vt in invalidation_check.all_vts:
      self.context.products.get_data('kythe_entries_files', dict)[vt.target] = entries_file(vt)
