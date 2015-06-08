# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BootstrapJvmToolsIntegrationTest(PantsRunIntegrationTest):
  def test_scala_java_collision(self):
    with temporary_dir(root_dir=self.workdir_root()) as artifact_cache:
      bootstrap_args = [
        'bootstrap.bootstrap-jvm-tools',
        "--write-artifact-caches=['{}']".format(artifact_cache),
        "--read-artifact-caches=['{}']".format(artifact_cache)
      ]

      # scala compilation should bootstrap and shade zinc
      pants_run = self.run_pants(bootstrap_args + ['compile', 'examples/src/scala/org/pantsbuild/example/hello'])
      self.assert_success(pants_run)
      self.assertTrue('[shade-zinc]' in pants_run.stdout_data)

      # java compilation should also bootstrap and shade zinc
      # because fingerprints are different for zinc and zinc-java tools
      pants_run = self.run_pants(bootstrap_args +
                                 ['compile',
                                  'examples/src/java/org/pantsbuild/example/hello/simple',
                                  '--compile-zinc-java-enabled'])
      self.assert_success(pants_run)
      self.assertTrue('[shade-zinc]' in pants_run.stdout_data)

      # but shouldn't bootstrap and shade after clean-all
      pants_run = self.run_pants(bootstrap_args +
                                 ['clean-all',
                                  'compile',
                                  'examples/src/java/org/pantsbuild/example/hello/simple',
                                  '--compile-zinc-java-enabled'])
      self.assert_success(pants_run)
      self.assertFalse('[shade-zinc]' in pants_run.stdout_data)

  def test_survive_clean_all(self):
    with temporary_dir(root_dir=self.workdir_root()) as artifact_cache:
      def run_compile():
        bootstrap_args = [
          'bootstrap.bootstrap-jvm-tools',
          "--write-artifact-caches=['{}']".format(artifact_cache),
          "--read-artifact-caches=['{}']".format(artifact_cache)
        ]
        compile_args = ['clean-all', 'compile', 'examples/src/scala/org/pantsbuild/example/hello']
        return self.run_pants(bootstrap_args + compile_args)

      # bootstrap
      pants_run = run_compile()
      self.assert_success(pants_run)
      self.assertTrue('[shade-zinc]' in pants_run.stdout_data)

      # compilation should reuse already shaded zinc
      pants_run = run_compile()
      self.assert_success(pants_run)
      self.assertFalse('[shade-zinc]' in pants_run.stdout_data)
