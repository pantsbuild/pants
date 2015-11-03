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

  def test_incremental_caching(self):
    with temporary_dir() as cache_dir, \
        self.temporary_workdir() as workdir, \
        temporary_dir(root_dir=get_buildroot()) as src_dir, \
        temporary_dir(root_dir=get_buildroot()) as dist_dir:

      config = {
        'DEFAULT': {
          'pants_distdir': dist_dir
        },
        'cache.compile.zinc': {'write_to': [cache_dir], 'read_from': [cache_dir]},
        'compile.zinc': {'incremental_caching': True },
      }

      srcfile = os.path.join(src_dir, 'org', 'pantsbuild', 'cachetest', 'A.java')
      buildfile = os.path.join(src_dir, 'org', 'pantsbuild', 'cachetest', 'BUILD')
      runtime_classpath = os.path.join(dist_dir, 'runtime_classpath')

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
      self.assertEqual(len(os.listdir(runtime_classpath)), 1)
      classes_symlink_folder = os.path.join(runtime_classpath, os.listdir(runtime_classpath)[0])
      real_classes1 = os.path.realpath(os.path.join(classes_symlink_folder, 'classes.jar'))

      self.create_file(srcfile,
                       dedent("""package org.pantsbuild.cachetest;
                            class A {}
                            class NotMain {}"""))
      # Caches values A.class, NotMain.class and leaves them on the filesystem
      self.run_compile(cachetest_spec, config, workdir)

      # symlink should be updated
      real_classes2 = os.path.realpath(os.path.join(classes_symlink_folder, 'z.jar'))
      self.assertNotEqual(real_classes1, real_classes2)

      self.create_file(srcfile,
                       dedent("""package org.pantsbuild.cachetest;
                          class A {}
                          class Main {}"""))

      # Should cause NotMain.class to be removed
      self.run_compile(cachetest_spec, config, workdir)

      # symlink should be changed back
      real_classes3 = os.path.realpath(os.path.join(classes_symlink_folder, 'z.jar'))
      self.assertEqual(real_classes1, real_classes3)

      root = os.path.join(workdir, 'compile', 'jvm', 'zinc')
      # One target.
      self.assertEqual(len(os.listdir(root)), 1)
      target_workdir_root = os.path.join(root, os.listdir(root)[0])
      target_workdirs = os.listdir(target_workdir_root)
      # Two workdirs.
      self.assertEqual(len(target_workdirs), 2)

      def classfiles(d):
        cd = os.path.join(target_workdir_root, d, 'classes', 'org', 'pantsbuild', 'cachetest')
        return sorted(os.listdir(cd))

      # One workdir should contain NotMain, and the other should contain Main.
      self.assertEquals(sorted(classfiles(w) for w in target_workdirs),
                        sorted([['A.class', 'Main.class'], ['A.class', 'NotMain.class']]))

  def test_no_incremental_caching_flag(self):
    """Tests that with --no-incremental-caching, we don't write incremental artifacts."""
    with temporary_dir() as cache_dir, \
        self.temporary_workdir() as workdir, \
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
