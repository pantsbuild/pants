# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BootstrapJvmToolsIntegrationTest(PantsRunIntegrationTest):

  def test_scala_java_reuse(self):
    with temporary_dir(root_dir=self.workdir_root()) as artifact_cache:
      bootstrap_args = [
        'bootstrap.bootstrap-jvm-tools',
        "--cache-write-to=['{}']".format(artifact_cache),
        "--cache-read-from=['{}']".format(artifact_cache)
      ]

      # Scala compilation should bootstrap and shade zinc.
      pants_run = self.run_pants(bootstrap_args + ['compile', 'examples/src/scala/org/pantsbuild/example/hello'])
      self.assert_success(pants_run)
      self.assertTrue('[shade-zinc]' in pants_run.stdout_data)

      # Java compilation shouldn't bootstrap and shade zinc after clean-all.
      pants_run = self.run_pants(bootstrap_args +
                                 ['clean-all',
                                  'compile',
                                  'examples/src/java/org/pantsbuild/example/hello/simple',
                                  '--compile-zinc-java-enabled'])
      self.assert_success(pants_run)
      self.assertFalse('[shade-zinc]' in pants_run.stdout_data)
