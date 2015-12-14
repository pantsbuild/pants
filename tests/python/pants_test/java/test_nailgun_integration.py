# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestNailgunIntegration(PantsRunIntegrationTest):
  def test_scala_repl_helloworld_input(self):
    """Integration test to exercise possible closed-loop breakages in NailgunClient, NailgunSession
    and InputReader.
    """
    target = 'examples/src/scala/org/pantsbuild/example/hello/welcome'
    pants_run = self.run_pants(
      command=['repl', target, '--quiet'],
      stdin_data=(
        'import org.pantsbuild.example.hello.welcome.WelcomeEverybody\n'
        'println(WelcomeEverybody("World" :: Nil).head)\n'
      ),
      # Override the PANTS_CONFIG_OVERRIDE="['pants.travis-ci.ini']" used within TravisCI to enable
      # nailgun usage for the purpose of exercising that stack in the integration test.
      config={'DEFAULT': {'use_nailgun': True}}
    )
    self.assert_success(pants_run)
    self.assertIn('Hello, World!', pants_run.stdout_data.splitlines())
