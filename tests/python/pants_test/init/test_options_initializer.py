# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.engine.environment import CompleteEnvironment
from pants.engine.internals.scheduler import ExecutionError
from pants.init.options_initializer import OptionsInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper


class OptionsInitializerTest(unittest.TestCase):
    def test_invalid_version(self) -> None:
        options_bootstrapper = OptionsBootstrapper.create(
            env={},
            args=["--backend-packages=[]", "--pants-version=99.99.9999"],
            allow_pantsrc=False,
        )

        env = CompleteEnvironment({})
        with self.assertRaises(ExecutionError):
            OptionsInitializer(options_bootstrapper).build_config_and_options(
                options_bootstrapper, env, raise_=True
            )

    def test_global_options_validation(self) -> None:
        # Specify an invalid combination of options.
        ob = OptionsBootstrapper.create(
            env={}, args=["--backend-packages=[]", "--remote-execution"], allow_pantsrc=False
        )
        env = CompleteEnvironment({})
        with self.assertRaises(ExecutionError) as exc:
            OptionsInitializer(ob).build_config_and_options(ob, env, raise_=True)
        self.assertIn("The `--remote-execution` option requires", str(exc.exception))
