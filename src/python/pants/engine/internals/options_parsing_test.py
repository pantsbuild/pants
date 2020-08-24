# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.rules import QueryRule, SubsystemRule
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import GLOBAL_SCOPE, Scope, ScopedOptions
from pants.python.python_setup import PythonSetup
from pants.testutil.engine_util import Params
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.test_base import TestBase
from pants.util.logging import LogLevel


class TestEngineOptionsParsing(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            SubsystemRule(PythonSetup),
            QueryRule(ScopedOptions, (Scope, OptionsBootstrapper)),
        )

    def test_options_parse_scoped(self):
        options_bootstrapper = create_options_bootstrapper(
            args=["-ldebug"], env=dict(PANTS_PANTSD="True", PANTS_BUILD_IGNORE='["ignoreme/"]')
        )
        global_options = self.request_product(
            ScopedOptions, Params(Scope(GLOBAL_SCOPE), options_bootstrapper)
        )
        python_setup_options = self.request_product(
            ScopedOptions, Params(Scope("python-setup"), options_bootstrapper)
        )

        self.assertEqual(global_options.options.level, LogLevel.DEBUG)
        self.assertEqual(global_options.options.pantsd, True)
        self.assertEqual(global_options.options.build_ignore, ["ignoreme/"])

        self.assertEqual(python_setup_options.options.platforms, ["current"])

    def test_options_parse_memoization(self):
        # Confirm that re-executing with a new-but-identical Options object results in memoization.

        def parse(ob):
            params = Params(Scope(str(GLOBAL_SCOPE)), ob)
            return self.request_product(ScopedOptions, params)

        # If two OptionsBootstrapper instances are not equal, memoization will definitely not kick in.
        one_opts = create_options_bootstrapper()
        two_opts = create_options_bootstrapper()
        self.assertEqual(one_opts, two_opts)
        self.assertEqual(hash(one_opts), hash(two_opts))

        # If they are equal, executing parsing on them should result in a memoized object.
        one = parse(one_opts)
        two = parse(two_opts)
        self.assertEqual(one, two)
        self.assertIs(one, two)
