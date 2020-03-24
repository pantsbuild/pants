# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from io import StringIO
from typing import Any, Dict, Iterable, Optional

from pants.engine.console import Console
from pants.engine.fs import Workspace
from pants.engine.goal import Goal
from pants.engine.selectors import Params
from pants.init.options_initializer import BuildConfigInitializer
from pants.init.specs_calculator import SpecsCalculator
from pants.option.global_options import GlobalOptions
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase
from pants.util.meta import classproperty


class GoalRuleTestBase(TestBase):
    """A baseclass useful for testing a Goal defined as a @goal_rule.

    :API: public
    """

    @classproperty
    def goal_cls(cls):
        """Subclasses must return the Goal type to test.

        :API: public
        """
        raise NotImplementedError()

    def setUp(self):
        super().setUp()

        if not issubclass(self.goal_cls, Goal):
            raise AssertionError(f"goal_cls() must return a Goal subclass, got {self.goal_cls}")

    def execute_rule(
        self,
        args: Optional[Iterable[str]] = None,
        global_args: Optional[Iterable[str]] = None,
        env: Optional[Dict[str, str]] = None,
        exit_code: int = 0,
        additional_params: Optional[Iterable[Any]] = None,
    ) -> str:
        """Executes the @goal_rule for this test class.

        :API: public

        Returns the text output of the task.
        """
        # Create an OptionsBootstrapper for these args/env, and a captured Console instance.
        options_bootstrapper = create_options_bootstrapper(
            args=(*(global_args or []), self.goal_cls.name, *(args or [])), env=env,
        )
        BuildConfigInitializer.get(options_bootstrapper)
        full_options = options_bootstrapper.get_full_options(
            [*GlobalOptions.known_scope_infos(), *self.goal_cls.subsystem_cls.known_scope_infos()]
        )
        stdout, stderr = StringIO(), StringIO()
        console = Console(stdout=stdout, stderr=stderr)
        scheduler = self.scheduler
        workspace = Workspace(scheduler)

        # Run for the target specs parsed from the args.
        specs = SpecsCalculator.parse_specs(full_options.specs, self.build_root)
        params = Params(
            specs.provided_specs,
            console,
            options_bootstrapper,
            workspace,
            *(additional_params or []),
        )
        actual_exit_code = self.scheduler.run_goal_rule(self.goal_cls, params)

        # Flush and capture console output.
        console.flush()
        stdout_val = stdout.getvalue()
        stderr_val = stderr.getvalue()

        assert (
            exit_code == actual_exit_code
        ), f"Exited with {actual_exit_code} (expected {exit_code}):\nstdout:\n{stdout_val}\nstderr:\n{stderr_val}"

        return stdout_val

    def assert_entries(self, sep, *output, **kwargs):
        """Verifies the expected output text is flushed by the console task under test.

        NB: order of entries is not tested, just presence.

        :API: public

        sep:      the expected output separator.
        *output:  the output entries expected between the separators
        **kwargs: additional kwargs passed to execute_rule.
        """
        # We expect each output line to be suffixed with the separator, so for , and [1,2,3] we expect:
        # '1,2,3,' - splitting this by the separator we should get ['1', '2', '3', ''] - always an extra
        # empty string if the separator is properly always a suffix and not applied just between
        # entries.
        self.assertEqual(
            sorted(list(output) + [""]), sorted((self.execute_rule(**kwargs)).split(sep))
        )

    def assert_console_output(self, *output, **kwargs):
        """Verifies the expected output entries are emitted by the console task under test.

        NB: order of entries is not tested, just presence.

        :API: public

        *output:  the expected output entries
        **kwargs: additional kwargs passed to execute_rule.
        """
        self.assertEqual(sorted(output), sorted(self.execute_rule(**kwargs).splitlines()))

    def assert_console_output_contains(self, output, **kwargs):
        """Verifies the expected output string is emitted by the console task under test.

        :API: public

        output:  the expected output entry(ies)
        **kwargs: additional kwargs passed to execute_rule.
        """
        self.assertIn(output, self.execute_rule(**kwargs))

    def assert_console_output_ordered(self, *output, **kwargs):
        """Verifies the expected output entries are emitted by the console task under test.

        NB: order of entries is tested.

        :API: public

        *output:  the expected output entries in expected order
        **kwargs: additional kwargs passed to execute_rule.
        """
        self.assertEqual(list(output), self.execute_rule(**kwargs).splitlines())

    def assert_console_raises(self, exception, **kwargs):
        """Verifies the expected exception is raised by the console task under test.

        :API: public

        **kwargs: additional kwargs are passed to execute_rule.
        """
        with self.assertRaises(exception):
            self.execute_rule(**kwargs)
