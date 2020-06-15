# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.selectors import Params
from pants.init.options_initializer import BuildConfigInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import GLOBAL_SCOPE, Scope, ScopedOptions
from pants.testutil.test_base import TestBase
from pants.util.logging import LogLevel


class TestEngineOptionsParsing(TestBase):
    def _ob(self, args=tuple(), env=tuple()):
        self.create_file("pants.toml")
        options_bootstrap = OptionsBootstrapper.create(args=tuple(args), env=dict(env),)
        # NB: BuildConfigInitializer has sideeffects on first-run: in actual usage, these
        # sideeffects will happen during setup. We force them here.
        BuildConfigInitializer.get(options_bootstrap)
        return options_bootstrap

    def test_options_parse_scoped(self):
        options_bootstrapper = self._ob(
            args=["./pants", "-ldebug", "binary", "src/python::"],
            env=dict(PANTS_PANTSD="True", PANTS_BINARIES_BASEURLS='["https://bins.com"]'),
        )

        global_options_params = Params(Scope(str(GLOBAL_SCOPE)), options_bootstrapper)
        python_setup_options_params = Params(Scope(str("python-setup")), options_bootstrapper)
        global_options, python_setup_options = self.scheduler.product_request(
            ScopedOptions, [global_options_params, python_setup_options_params],
        )

        self.assertEqual(global_options.options.level, LogLevel.DEBUG)
        self.assertEqual(global_options.options.pantsd, True)
        self.assertEqual(global_options.options.binaries_baseurls, ["https://bins.com"])

        self.assertEqual(python_setup_options.options.platforms, ["current"])

    def test_options_parse_memoization(self):
        # Confirm that re-executing with a new-but-identical Options object results in memoization.
        def ob():
            return self._ob(args=["./pants", "-ldebug", "binary", "src/python::"])

        def parse(ob):
            params = Params(Scope(str(GLOBAL_SCOPE)), ob)
            return self.request_single_product(ScopedOptions, params)

        # If two OptionsBootstrapper instances are not equal, memoization will definitely not kick in.
        one_opts = ob()
        two_opts = ob()
        self.assertEqual(one_opts, two_opts)
        self.assertEqual(hash(one_opts), hash(two_opts))

        # If they are equal, executing parsing on them should result in a memoized object.
        one = parse(one_opts)
        two = parse(two_opts)
        self.assertEqual(one, two)
        self.assertIs(one, two)
