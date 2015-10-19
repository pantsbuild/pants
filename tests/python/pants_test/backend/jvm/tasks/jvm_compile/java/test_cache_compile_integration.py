# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class CacheCompileIntegrationTest(BaseCompileIT):
  def run_compile(self, target_spec, config, workdir):
    args = ['compile', target_spec]
    pants_run = self.run_pants_with_workdir(args, workdir, config)
    self.assert_success(pants_run)

  def create_file(self, path, value):
    with safe_open(path, 'w') as f:
      f.write(value)

  def test_stale_artifacts_rmd_when_cache_used_with_zinc(self):
    self._do_test_stale_artifacts_rmd_when_cache_used()

  def _do_test_stale_artifacts_rmd_when_cache_used(self):
    with temporary_dir() as cache_dir, \
        temporary_dir(root_dir=self.workdir_root()) as workdir, \
        temporary_dir(root_dir=get_buildroot()) as src_dir:

      config = {
        'cache.compile.zinc': {'write_to': [cache_dir], 'read_from': [cache_dir]},
        'compile.zinc': {'incremental_caching': True },
      }

      srcfile = os.path.join(src_dir, 'org', 'pantsbuild', 'cachetest', 'A.java')
      buildfile = os.path.join(src_dir, 'org', 'pantsbuild', 'cachetest', 'BUILD')

      self.create_file(srcfile,
                       dedent("""package org.pantsbuild.cachetest;
                          class A {}
                          class Main {}"""))
      self.create_file(buildfile,
                       dedent("""java_library(name='cachetest',
                                       sources=['A.java']
                          )"""))

      cachetest_spec = os.path.join(os.path.basename(src_dir), 'org', 'pantsbuild',
                                    'cachetest:cachetest')

      # Caches values A.class, Main.class
      self.run_compile(cachetest_spec, config, workdir)

      self.create_file(srcfile,
                       dedent("""package org.pantsbuild.cachetest;
                            class A {}
                            class NotMain {}"""))
      # Caches values A.class, NotMain.class and leaves them on the filesystem
      self.run_compile(cachetest_spec, config, workdir)

      self.create_file(srcfile,
                       dedent("""package org.pantsbuild.cachetest;
                          class A {}
                          class Main {}"""))

      # Should cause NotMain.class to be removed
      self.run_compile(cachetest_spec, config, workdir)

      cachetest_id = cachetest_spec.replace(':', '.').replace(os.sep, '.')

      class_file_dir = os.path.join(workdir,
                                      'compile',
                                      'jvm',
                                      'zinc',
                                      'isolated-classes',
                                      cachetest_id,
                                      'org',
                                      'pantsbuild',
                                      'cachetest',
                                      )
      self.assertEqual(sorted(os.listdir(class_file_dir)), sorted(['A.class', 'Main.class']))

  def test_incremental_caching(self):
    """Tests that with --no-incremental-caching, we don't write incremental artifacts."""
    with temporary_dir() as cache_dir, \
        temporary_dir(root_dir=self.workdir_root()) as workdir, \
        temporary_dir(root_dir=get_buildroot()) as src_dir:

      def config(incremental_caching):
        return {
          'cache.compile.zinc': {'write_to': [cache_dir], 'read_from': [cache_dir]},
          'compile.zinc': {'incremental_caching': incremental_caching},
        }

      srcfile = os.path.join(src_dir, 'A.java')
      buildfile = os.path.join(src_dir, 'BUILD')
      spec = os.path.join(src_dir, ':cachetest')
      artifact_dir = os.path.join(cache_dir,
                                  ZincCompile.stable_name(),
                                  '{}.cachetest'.format(os.path.basename(src_dir)))

      self.create_file(srcfile, """class A {}""")
      self.create_file(buildfile, """java_library(name='cachetest', sources=['A.java'])""")


      # Confirm that the result is one cached artifact.
      self.run_compile(spec, config(False), workdir)
      clean_artifacts = os.listdir(artifact_dir)
      self.assertEquals(1, len(clean_artifacts))

      # Modify the file, and confirm that artifacts haven't changed.
      self.create_file(srcfile, """final class A {}""")
      self.run_compile(spec, config(False), workdir)
      self.assertEquals(clean_artifacts, os.listdir(artifact_dir))

      # Modify again, this time with incremental and confirm that we have a second artifact.
      self.create_file(srcfile, """public final class A {}""")
      self.run_compile(spec, config(True), workdir)
      self.assertEquals(2, len(os.listdir(artifact_dir)))
