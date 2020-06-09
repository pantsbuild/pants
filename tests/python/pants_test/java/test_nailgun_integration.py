# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class TestNailgunIntegration(PantsRunIntegrationTest):
    target = "examples/src/scala/org/pantsbuild/example/hello/welcome"

    def test_scala_repl_helloworld_input(self):
        """Integration test to exercise possible closed-loop breakages in NailgunClient,
        NailgunSession and InputReader."""
        pants_run = self.run_pants(
            command=["repl", self.target, "--quiet"],
            stdin_data=(
                "import org.pantsbuild.example.hello.welcome.WelcomeEverybody\n"
                'println(WelcomeEverybody("World" :: Nil).head)\n'
            ),
            # Override the PANTS_CONFIG_FILES="pants.travis-ci.toml" used within TravisCI to enable
            # nailgun usage for the purpose of exercising that stack in the integration test.
            config={"DEFAULT": {"execution_strategy": "nailgun"}},
        )
        self.assert_success(pants_run)
        self.assertIn("Hello, World!", pants_run.stdout_data.splitlines())

    def test_nailgun_connect_timeout(self):
        pants_run = self.run_pants(
            ["compile", self.target],
            # Override the PANTS_CONFIG_FILES="pants.travis-ci.toml" used within TravisCI to enable
            # nailgun usage for the purpose of exercising that stack in the integration test.
            config={
                "DEFAULT": {"execution_strategy": "nailgun"},
                "compile.rsc": {"nailgun_timeout_seconds": "0.00002"},
            },
        )
        self.assert_failure(pants_run)
        self.assertRegex(
            pants_run.stdout_data, r"""\<no nailgun connection>.* Failed to read nailgun output"""
        )
