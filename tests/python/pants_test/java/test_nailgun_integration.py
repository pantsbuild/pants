# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.py2_compat import assertRegex


class TestNailgunIntegration(PantsRunIntegrationTest):
  target = 'examples/src/scala/org/pantsbuild/example/hello/welcome'

  def test_scala_repl_helloworld_input(self):
    """Integration test to exercise possible closed-loop breakages in NailgunClient, NailgunSession
    and InputReader.
    """
    pants_run = self.run_pants(
      command=['repl', self.target, '--quiet'],
      stdin_data=(
        'import org.pantsbuild.example.hello.welcome.WelcomeEverybody\n'
        'println(WelcomeEverybody("World" :: Nil).head)\n'
      ),
      # Override the PANTS_CONFIG_FILES="pants.travis-ci.ini" used within TravisCI to enable
      # nailgun usage for the purpose of exercising that stack in the integration test.
      config={'DEFAULT': {'execution_strategy': 'nailgun'}}
    )
    self.assert_success(pants_run)
    self.assertIn('Hello, World!', pants_run.stdout_data.splitlines())

  def test_nailgun_connect_timeout(self):
    pants_run = self.run_pants(
      ['compile', self.target],
      # Override the PANTS_CONFIG_FILES="pants.travis-ci.ini" used within TravisCI to enable
      # nailgun usage for the purpose of exercising that stack in the integration test.
      config={'DEFAULT': {'execution_strategy': 'nailgun'},
              'compile.zinc': {'nailgun_timeout_seconds': '0.00002'}}
    )
    self.assert_failure(pants_run)
    assertRegex(self, pants_run.stdout_data, """\
compile\\(examples/src/java/org/pantsbuild/example/hello/greet:greet\\) failed: \
Problem launching via <no nailgun connection> command org\\.pantsbuild\\.zinc\\.compiler\\.Main .*: \
Failed to read nailgun output after 2e\-05 seconds!""")
