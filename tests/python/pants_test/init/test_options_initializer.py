# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.unions import UnionMembership
from pants.init.options_initializer import OptionsInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper


class OptionsInitializerTest(unittest.TestCase):
    def test_invalid_version(self) -> None:
        options_bootstrapper = OptionsBootstrapper.create(
            env={},
            args=["--backend-packages=[]", "--pants-version=99.99.9999"],
            allow_pantsrc=False,
        )

        env = CompleteEnvironmentVars({})
        initializer = OptionsInitializer(options_bootstrapper)
        build_config = initializer.build_config(options_bootstrapper, env)
        with self.assertRaises(ExecutionError):
            initializer.options(
                options_bootstrapper,
                env,
                build_config,
                union_membership=UnionMembership({}),
                raise_=True,
            )

    def test_global_options_validation(self) -> None:
        # Specify an invalid combination of options.
        ob = OptionsBootstrapper.create(
            env={},
            args=["--backend-packages=[]", "--no-watch-filesystem", "--loop"],
            allow_pantsrc=False,
        )
        env = CompleteEnvironmentVars({})
        initializer = OptionsInitializer(ob)
        build_config = initializer.build_config(ob, env)
        with self.assertRaises(ExecutionError) as exc:
            initializer.options(
                ob, env, build_config, union_membership=UnionMembership({}), raise_=True
            )
        self.assertIn(
            "The `--no-watch-filesystem` option may not be set if `--pantsd` or `--loop` is set.",
            str(exc.exception),
        )
