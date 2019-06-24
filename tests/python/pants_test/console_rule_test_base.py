# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from io import StringIO

from pants.engine.console import Console
from pants.engine.goal import Goal
from pants.engine.selectors import Params
from pants.init.options_initializer import BuildConfigInitializer
from pants.init.target_roots_calculator import TargetRootsCalculator
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.meta import classproperty
from pants_test.test_base import TestBase


class ConsoleRuleTestBase(TestBase):
  """A baseclass useful for testing a Goal defined as a @console_rule.

  :API: public
  """

  _implicit_args = tuple(['--pants-config-files=[]'])

  @classproperty
  def goal_cls(cls):
    """Subclasses must return the Goal type to test.

    :API: public
    """
    raise NotImplementedError()

  def setUp(self):
    super().setUp()

    if not issubclass(self.goal_cls, Goal):
      raise AssertionError('goal_cls() must return a Goal subclass, got {}'.format(self.goal_cls))

  def execute_rule(self, args=tuple(), env=tuple(), exit_code=0):
    """Executes the @console_rule for this test class.

    :API: public

    Returns the text output of the task.
    """
    # Create an OptionsBootstrapper for these args/env, and a captured Console instance.
    args = self._implicit_args + (self.goal_cls.name,) + tuple(args)
    env = dict(env)
    options_bootstrapper = OptionsBootstrapper.create(args=args, env=env)
    BuildConfigInitializer.get(options_bootstrapper)
    full_options = options_bootstrapper.get_full_options(list(self.goal_cls.Options.known_scope_infos()))
    stdout, stderr = StringIO(), StringIO()
    console = Console(stdout=stdout, stderr=stderr)

    # Run for the target specs parsed from the args.
    specs = TargetRootsCalculator.parse_specs(full_options.target_specs, self.build_root)
    params = Params(specs, console, options_bootstrapper)
    actual_exit_code = self.scheduler.run_console_rule(self.goal_cls, params)

    # Flush and capture console output.
    console.flush()
    stdout = stdout.getvalue()
    stderr = stderr.getvalue()

    self.assertEqual(
        exit_code,
        actual_exit_code,
        "Exited with {} (expected {}):\nstdout:\n{}\nstderr:\n{}".format(actual_exit_code, exit_code, stdout, stderr)
      )

    return stdout

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
    self.assertEqual(sorted(list(output) + ['']), sorted((self.execute_rule(**kwargs)).split(sep)))

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
