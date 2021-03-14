# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.base.exceptions import BuildConfigurationError
from pants.engine.environment import CompleteEnvironment
from pants.init.options_initializer import OptionsInitializer
from pants.option.errors import OptionsError
from pants.option.options_bootstrapper import OptionsBootstrapper


class OptionsInitializerTest(unittest.TestCase):
    def test_invalid_version(self):
        options_bootstrapper = OptionsBootstrapper.create(
            env={},
            args=["--backend-packages=[]", "--pants-version=99.99.9999"],
            allow_pantsrc=False,
        )

        env = CompleteEnvironment({})
        with self.assertRaises(BuildConfigurationError):
            OptionsInitializer(options_bootstrapper, env).build_config_and_options(
                options_bootstrapper, env, raise_=True
            )

    def test_global_options_validation(self):
        # Specify an invalid combination of options.
        ob = OptionsBootstrapper.create(
            env={}, args=["--backend-packages=[]", "--remote-execution"], allow_pantsrc=False
        )
        env = CompleteEnvironment({})
        with self.assertRaises(OptionsError) as exc:
            OptionsInitializer(ob, env).build_config_and_options(ob, env, raise_=True)
        self.assertIn("The `--remote-execution` option requires", str(exc.exception))
