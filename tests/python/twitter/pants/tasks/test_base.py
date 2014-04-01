# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from StringIO import StringIO
from contextlib import closing
from optparse import OptionGroup, OptionParser

import pytest
from twitter.common.collections import maybe_list

from pants.base.context_utils import create_config, create_context, create_run_tracker
from pants.base.target import Target
from pants.base_build_root_test import BaseBuildRootTest
from pants.commands.goal import SpecParser
from pants.goal import Context, Mkflag
from pants.tasks import Task
from pants.tasks.console_task import ConsoleTask


def prepare_task(task_type, config=None, args=None, targets=None, **kwargs):
  """Prepares a Task for execution.

  task_type: The class of the Task to create.
  config: An optional string representing the contents of a pants.ini config.
  args: optional list of command line flags, these should be prefixed with '--test-'.
  targets: optional list of Target objects passed on the command line.
  **kwargs: Any additional args the Task subclass constructor takes beyond the required context.

  Returns a new Task ready to execute.
  """

  assert issubclass(task_type, Task), 'task_type must be a Task subclass, got %s' % task_type

  config = create_config(config or '')

  parser = OptionParser()
  option_group = OptionGroup(parser, 'test')
  mkflag = Mkflag('test')
  task_type.setup_parser(option_group, args, mkflag)
  options, _ = parser.parse_args(args or [])

  run_tracker = create_run_tracker()

  context = Context(config, options, run_tracker, targets or [])
  return task_type(context, **kwargs)


class TaskTest(BaseBuildRootTest):
  """A baseclass useful for testing Tasks."""

  @classmethod
  def targets(cls, spec):
    """Resolves a target spec to one or more Target objects.

    spec: Either BUILD target address or else a target glob using the siblings ':' or
          descendants '::' suffixes.

    Returns the set of all Targets found.
    """
    return set(target for target, _ in SpecParser(cls.build_root).parse(spec) if target)

  def assertDeps(self, target, expected_deps=None):
    """Check that actual and expected dependencies of the given target match.

    :param target: :class:`pants.base.target.Target` to check
      dependencies of.
    :param expected_deps: :class:`pants.base.target.Target` or list of
      ``Target`` instances that are expected dependencies of ``target``.
    """
    expected_deps_list = maybe_list(expected_deps or [], expected_type=Target)
    self.assertEquals(set(expected_deps_list), set(target.dependencies))


class ConsoleTaskTest(TaskTest):
  """A baseclass useful for testing ConsoleTasks."""

  @classmethod
  def setUpClass(cls):
    super(ConsoleTaskTest, cls).setUpClass()

    task_type = cls.task_type()
    assert issubclass(task_type, ConsoleTask), \
        'task_type() must return a ConsoleTask subclass, got %s' % task_type

  @classmethod
  def task_type(cls):
    """Subclasses must return the type of the ConsoleTask subclass under test."""
    raise NotImplementedError()

  def execute_task(self, config=None, args=None, targets=None, extra_targets=None):
    """Creates a new task and executes it with the given config, command line args and targets.

    config:        an optional string representing the contents of a pants.ini config.
    args:          optional list of command line flags, these should be prefixed with '--test-'.
    targets:       optional list of Target objects passed on the command line.
    extra_targets: optional list of extra targets in the context in addition to those passed on the
                   command line
    Returns the text output of the task.
    """
    with closing(StringIO()) as output:
      task = prepare_task(self.task_type(), config=config, args=args, targets=targets,
                          outstream=output)
      task.execute(list(targets or ()) + list(extra_targets or ()))
      return output.getvalue()

  def execute_console_task(self, config=None, args=None, targets=None, extra_targets=None,
                           **kwargs):
    """Creates a new task and executes it with the given config, command line args and targets.

    config:        an optional string representing the contents of a pants.ini config.
    args:          optional list of command line flags, these should be prefixed with '--test-'.
    targets:       optional list of Target objects passed on the command line.
    extra_targets: optional list of extra targets in the context in addition to those passed on the
                   command line
    **kwargs: additional kwargs are passed to the task constructor.

    Returns the list of items returned from invoking the console task's console_output method.
    """
    task = prepare_task(self.task_type(), config=config, args=args, targets=targets, **kwargs)
    return list(task.console_output(list(targets or ()) + list(extra_targets or ())))

  def assert_entries(self, sep, *output, **kwargs):
    """Verifies the expected output text is flushed by the console task under test.

    NB: order of entries is not tested, just presence.

    sep:      the expected output separator.
    *output:  the output entries expected between the separators
    **kwargs: additional kwargs are passed to the task constructor except for config args, targets
              and extra_targets which are passed to execute_task.
    """
    # We expect each output line to be suffixed with the separator, so for , and [1,2,3] we expect:
    # '1,2,3,' - splitting this by the separator we should get ['1', '2', '3', ''] - always an extra
    # empty string if the separator is properly always a suffix and not applied just between
    # entries.
    self.assertEqual(sorted(list(output) + ['']), sorted((self.execute_task(**kwargs)).split(sep)))

  def assert_console_output(self, *output, **kwargs):
    """Verifies the expected output entries are emitted by the console task under test.

    NB: order of entries is not tested, just presence.

    *output:  the expected output entries
    **kwargs: additional kwargs are passed to the task constructor except for config args, targets
              and extra_targets which are passed to execute_console_task.
    """
    self.assertEqual(sorted(output), sorted(self.execute_console_task(**kwargs)))

  def assert_console_raises(self, exception, **kwargs):
    """Verifies the expected exception is raised by the console task under test.

    **kwargs: additional kwargs are passed to the task constructor except for config args, targets
              and extra_targets which are passed to execute_console_task.
    """
    with pytest.raises(exception):
      self.execute_console_task(**kwargs)
