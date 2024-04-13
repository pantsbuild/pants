# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.internals.scheduler import ExecutionError
from pants.init.options_initializer import OptionsInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil import rule_runner


class OptionsInitializerTest(unittest.TestCase):
    def test_invalid_version(self) -> None:
        options_bootstrapper = OptionsBootstrapper.create(
            env={},
            args=["--backend-packages=[]", "--pants-version=99.99.9999"],
            allow_pantsrc=False,
        )

        env = CompleteEnvironmentVars({})
        initializer = OptionsInitializer(options_bootstrapper, rule_runner.EXECUTOR)
        with self.assertRaises(ExecutionError):
            initializer.build_config(options_bootstrapper, env)

    def test_global_options_validation(self) -> None:
        # Specify an invalid combination of options.
        ob = OptionsBootstrapper.create(
            env={},
            args=["--backend-packages=[]", "--no-watch-filesystem", "--loop"],
            allow_pantsrc=False,
        )
        env = CompleteEnvironmentVars({})
        initializer = OptionsInitializer(ob, rule_runner.EXECUTOR)
        with self.assertRaises(ExecutionError) as exc:
            initializer.build_config(ob, env)
        self.assertIn(
            "The `--no-watch-filesystem` option may not be set if `--pantsd` or `--loop` is set.",
            str(exc.exception),
        )
