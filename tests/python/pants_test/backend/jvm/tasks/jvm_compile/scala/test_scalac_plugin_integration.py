# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants_test.backend.jvm.tasks.jvm_compile.scala.base_scalac_plugin_integration_test import (
    ScalacPluginIntegrationTestBase,
)


@pytest.mark.skip(reason="takes too long")
class ScalacPluginIntegrationTest(ScalacPluginIntegrationTestBase):
    example_dir = "examples/src/scala/org/pantsbuild/example/scalac/plugin"

    def _do_test(self, expected_args, config, target):
        with self.temporary_workdir() as workdir:
            pants_run = self.run_pants_with_workdir(
                ["compile", f"{self.example_dir}:{target}"], workdir, config
            )
        self.assert_success(pants_run)
        self.assertIn(
            "SimpleScalacPlugin ran with {} args: {}".format(
                len(expected_args), " ".join(expected_args)
            ),
            pants_run.stdout_data,
        )

    # Note that in the terminology of this test, "global" means specified via options for
    # all targets, and "local" means specified on an individual target.
    def _do_test_global(self, args, extra_config={}, expected_args=None):
        config = self.with_global_plugin_enabled(self.with_global_plugin_args(args, extra_config))
        # Must compile the plugin explicitly, since there's no dep.
        self._do_test((expected_args or args), config, "global")

    def _do_test_local_with_global_args(self, args):
        config = self.with_global_plugin_args(args, {})
        self._do_test(args, config, "local_with_global_args")

    def test_global(self):
        self._do_test_global([])
        self._do_test_global(["abc"])
        self._do_test_global(["abc", "def"])

    def test_global_with_local_args(self):
        self._do_test(
            ["args", "from", "target", "global_with_local_args"],
            self.with_global_plugin_enabled(),
            "global_with_local_args",
        )

    def test_local_with_global_args(self):
        self._do_test_local_with_global_args([])
        self._do_test_local_with_global_args(["abc"])
        self._do_test_local_with_global_args(["abc", "def"])

    def test_local(self):
        self._do_test(["args", "from", "target", "local"], None, "local")

    def test_plugin_uses_other_plugin(self):
        # Test that a plugin can use another plugin:  While compiling simple_scalac_plugin
        # we will use other_simple_scalac_plugin (because it's globally specified).
        # This is a regression test for https://github.com/pantsbuild/pants/issues/4475.
        config = self.with_other_global_plugin_enabled(
            {"scala": {"scalac_plugin_args": {"other_simple_scalac_plugin": ["foo"]}}}
        )
        self._do_test(["args", "from", "target", "local"], config, "local")

    def test_compiler_option_sets_enabled_scalac_plugins(self):
        self._do_test_global(
            args=[],
            extra_config=self.with_compiler_option_sets_enabled_scalac_plugins(),
            expected_args=["abc", "def"],
        )
