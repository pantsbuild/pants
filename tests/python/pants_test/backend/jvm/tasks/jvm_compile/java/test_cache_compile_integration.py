# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import namedtuple
from textwrap import dedent

from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class Compile(namedtuple('Compile', ['srcfiles', 'config', 'artifact_count'])):
  pass


class CacheCompileIntegrationTest(BaseCompileIT):

  def run_compile(self, target_spec, config, workdir):
    args = ['compile', target_spec]
    pants_run = self.run_pants_with_workdir(args, workdir, config)
    self.assert_success(pants_run)

  def create_file(self, path, value):
    with safe_open(path, 'w') as f:
      f.write(value)

  def test_transitive_invalid_target_is_dep(self):
    with temporary_dir() as cache_dir, \
      temporary_dir(root_dir=get_buildroot()) as src_dir:

      config = {
        'cache.compile.zinc': {'write_to': [cache_dir], 'read_from': [cache_dir]},
        'compile.zinc': {'incremental_caching': True},
        'java': {'strict_deps': False},
      }
      target_dir = os.path.join(src_dir, 'org', 'pantsbuild', 'cachetest')
      a_srcfile = os.path.join(target_dir, 'A.java')
      b_srcfile = os.path.join(target_dir, 'B.java')
      c_srcfile = os.path.join(target_dir, 'C.java')
      buildfile = os.path.join(target_dir, 'BUILD')

      self.create_file(a_srcfile,
                       dedent("""package org.pantsbuild.cachetest;
                          class A {}
                          """))
      self.create_file(b_srcfile,
                       dedent("""package org.pantsbuild.cachetest;
                          class B {
                            A a;
                          }
                          """))
      self.create_file(c_srcfile,
                       dedent("""package org.pantsbuild.cachetest;
                          class C {
                            A a;
                          }
                          """))

      self.create_file(buildfile,
                       dedent("""
                          java_library(name='a',
                                       sources=['A.java']
                          )

                          java_library(name='b',
                                       sources=['B.java'],
                                       dependencies=[':a']
                          )

                          java_library(name='c',
                                       sources=['C.java'],
                                       dependencies=[':b']
                          )
                          """))

      c_spec = os.path.join(os.path.basename(src_dir), 'org', 'pantsbuild',
                                    'cachetest:c')

      with self.temporary_workdir() as workdir:
        self.run_compile(c_spec, config, workdir)
      # clean workdir

      # rm cache entries for a and b
      cache_dir_entries = os.listdir(os.path.join(cache_dir))
      zinc_dir = os.path.join(cache_dir, cache_dir_entries[0])
      c_or_a_cache_dirs = [subdir for subdir in os.listdir(zinc_dir)
                           if subdir.endswith('cachetest.a') or subdir.endswith('cachetest.c')]
      for subdir in c_or_a_cache_dirs:
        safe_rmtree(os.path.join(zinc_dir, subdir))

      # run compile
      with self.temporary_workdir() as workdir:
        self.run_compile(c_spec, config, workdir)

  def test_stale_artifacts_rmd_when_cache_used_with_zinc(self):
    with temporary_dir() as cache_dir, \
        self.temporary_workdir() as workdir, \
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

      root = os.path.join(workdir, 'compile', 'zinc')

      versioned_root = os.path.join(root, os.listdir(root)[0])
      self.assertEqual(len(os.listdir(root)), 1, 'Expected 1 task version.')

      target_root = os.path.join(root, os.listdir(root)[0])
      self.assertEqual(len(os.listdir(target_root)), 1, 'Expected 1 target.')

      target_workdir_root = os.path.join(versioned_root, os.listdir(versioned_root)[0])
      target_workdirs = os.listdir(target_workdir_root)
      self.assertEqual(len(target_workdirs), 3, 'Expected 3 workdirs (current, and two versioned).')
      self.assertIn('current', target_workdirs)

      def classfiles(d):
        cd = os.path.join(target_workdir_root, d, 'classes', 'org', 'pantsbuild', 'cachetest')
        return sorted(os.listdir(cd))

      # One workdir should contain NotMain, and the other should contain Main.
      self.assertEquals(sorted(classfiles(w) for w in target_workdirs if w != 'current'),
                        sorted([['A.class', 'Main.class'], ['A.class', 'NotMain.class']]))

  def test_incremental_caching(self):
    """Tests that with --no-incremental-caching, we don't write incremental artifacts."""

    srcfile = 'A.java'
    def config(incremental_caching):
      return { 'compile.zinc': {'incremental_caching': incremental_caching} }

    self._do_test_caching(
        Compile({srcfile: "class A {}"}, config(False), 1),
        Compile({srcfile: "final class A {}"}, config(False), 1),
        Compile({srcfile: "public final class A {}"}, config(True), 2),
    )

  def test_incremental(self):
    """Tests that with --no-incremental and --no-incremental-caching, we always write artifacts."""

    srcfile = 'A.java'
    config = {'compile.zinc': {'incremental': False, 'incremental_caching': False}}

    self._do_test_caching(
        Compile({srcfile: "class A {}"}, config, 1),
        Compile({srcfile: "final class A {}"}, config, 2),
        Compile({srcfile: "public final class A {}"}, config, 3),
    )

  def _do_test_caching(self, *compiles):
    """Tests that the given compiles within the same workspace produce the given artifact counts."""
    with temporary_dir() as cache_dir, \
        self.temporary_workdir() as workdir, \
        temporary_dir(root_dir=get_buildroot()) as src_dir:

      def complete_config(config):
        # Clone the input config and add cache settings.
        cache_settings = {'write_to': [cache_dir], 'read_from': [cache_dir]}
        return dict(config.items() + [('cache.compile.zinc', cache_settings)])

      buildfile = os.path.join(src_dir, 'BUILD')
      spec = os.path.join(src_dir, ':cachetest')
      artifact_dir = os.path.join(cache_dir,
                                  ZincCompile.stable_name(),
                                  '{}.cachetest'.format(os.path.basename(src_dir)))

      for c in compiles:
        # Clear the src directory and recreate the files.
        safe_mkdir(src_dir, clean=True)
        self.create_file(buildfile,
                        """java_library(name='cachetest', sources=rglobs('*.java', '*.scala'))""")
        for name, content in c.srcfiles.items():
          self.create_file(os.path.join(src_dir, name), content)

        # Compile, and confirm that we have the right count of artifacts.
        self.run_compile(spec, complete_config(c.config), workdir)
        self.assertEquals(c.artifact_count, len(os.listdir(artifact_dir)))


class CacheCompileIntegrationWithZjarsTest(CacheCompileIntegrationTest):
  _EXTRA_TASK_ARGS = ['--compile-zinc-use-classpath-jars']
