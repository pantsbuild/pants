# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent
from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_open
from pants.util.contextutil import temporary_dir
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class CacheCompileIntegrationTest(BaseCompileIT):
  def run_compile(self, target_spec, config, strategy, workdir):
    pants_run = self.run_pants_with_workdir(
      ['compile', 'compile.java', '--strategy={}'.format(strategy), '--partition-size-hint=1',
       target_spec,
       ],
      workdir, config)
    self.assert_success(pants_run)

  def create_file(self, path, value):
    with safe_open(path, 'w') as f:
      f.write(value)

  def test_stale_artifacts_rmd_when_cache_used(self):
    with temporary_dir() as cache_dir, \
        temporary_dir(root_dir=self.workdir_root()) as workdir, \
        temporary_dir(root_dir=get_buildroot()) as src_dir:
      config = {'cache.compile.java': {'write_to': [cache_dir], 'read_from': [cache_dir]}}

      self.create_file(os.path.join(src_dir, 'org', 'pantsbuild', 'cachetest', 'A.java'),
                       dedent("""package org.pantsbuild.cachetest;
                          class A {}
                          class Main {}"""))
      self.create_file(os.path.join(src_dir, 'org', 'pantsbuild', 'cachetest', 'BUILD'),
                       dedent("""java_library(name='cachetest',
                                       sources=['A.java']
                          )"""))

      cachetest_spec = os.path.join(os.path.basename(src_dir), 'org', 'pantsbuild',
                                    'cachetest:cachetest')

      # Caches values A.class, Main.class
      self.run_compile(cachetest_spec, config, 'isolated', workdir)

      self.create_file(os.path.join(src_dir, 'org', 'pantsbuild', 'cachetest', 'A.java'),
                       dedent("""package org.pantsbuild.cachetest;
                            class A {}
                            class NotMain {}"""))
      # Caches values A.class, NotMain.class and leaves them on the filesystem
      self.run_compile(cachetest_spec, config, 'isolated', workdir)

      self.create_file(os.path.join(src_dir, 'org', 'pantsbuild', 'cachetest', 'A.java'),
                       dedent("""package org.pantsbuild.cachetest;
                          class A {}
                          class Main {}"""))

      # Should cause NotMain.class to be removed
      self.run_compile(cachetest_spec, config, 'isolated', workdir)

      cachetest_id = cachetest_spec.replace(':', '.').replace(os.sep, '.')

      bad_artifact_dir = os.path.join(workdir,
                                      'compile',
                                      'jvm',
                                      'java',
                                      'isolated-classes',
                                      cachetest_id,
                                      'org',
                                      'pantsbuild',
                                      'cachetest',
                                      )
      self.assertEqual(os.listdir(bad_artifact_dir), ['A.class', 'Main.class'])