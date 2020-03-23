# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.util.collections import recursively_update
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class ScalacPluginIntegrationTestBase(BaseCompileIT):
    def with_global_plugin_enabled(self, config={}):
        recursively_update(config, {"scala": {"scalac_plugins": ["simple_scalac_plugin"]}})
        return config

    def with_global_plugin_args(self, args, config={}):
        if args is not None:
            recursively_update(
                config, {"scala": {"scalac_plugin_args": {"simple_scalac_plugin": args}}}
            )
        return config

    def with_other_global_plugin_enabled(self, config={}):
        recursively_update(config, {"scala": {"scalac_plugins": ["other_simple_scalac_plugin"]}})
        return config

    def with_compiler_option_sets_enabled_scalac_plugins(self, config={}):
        recursively_update(
            config,
            {
                "compile.rsc": {
                    "compiler_option_sets_enabled_args": {
                        "option-set-requiring-scalac-plugin": [
                            "-S-P:simple_scalac_plugin:abc",
                            "-S-P:simple_scalac_plugin:def",
                        ],
                    },
                    "compiler_option_sets_enabled_scalac_plugins": {
                        "option-set-requiring-scalac-plugin": ["simple_scalac_plugin"],
                    },
                }
            },
        )
        return config
