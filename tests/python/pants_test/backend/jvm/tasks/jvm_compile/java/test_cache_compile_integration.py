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
from pants.util.dirutil import safe_mkdir, safe_open
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
