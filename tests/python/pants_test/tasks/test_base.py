# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import subprocess
from contextlib import closing

from StringIO import StringIO

from twitter.common.collections import maybe_list

from pants.backend.core.tasks.task import Task

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.target import Target
from pants.goal.context import Context
from pants.goal.goal import Goal
from pants.option.global_options import register_global_options
from pants.option.options_bootstrapper import OptionsBootstrapper, register_bootstrap_options
from pants.option.options import Options
from pants_test.base_test import BaseTest
from pants_test.base.context_utils import create_config, create_run_tracker

def is_exe(name):
  result = subprocess.call(['which', name], stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT)
  return result == 0


class TaskTest(BaseTest):
  """A baseclass useful for testing Tasks."""

  @classmethod
  def task_type(cls):
    """Subclasses must return the type of the ConsoleTask subclass under test."""
    raise NotImplementedError()

  def prepare_task(self,
                   config=None,
                   args=None,
                   targets=None,
                   build_graph=None,
                   build_file_parser=None,
                   address_mapper=None,
                   console_outstream=None,
                   workspace=None):
    """Prepares a Task for execution.

    task_type: The class of the Task to create.
    config: An optional string representing the contents of a pants.ini config.
    args: optional list of command line flags, these should be prefixed with '--test-'.
    targets: optional list of Target objects passed on the command line.

    Returns a new Task ready to execute.
    """

    task_type = self.task_type()
    assert issubclass(task_type, Task), 'task_type must be a Task subclass, got %s' % task_type

    config = create_config(config or '')
    workdir = os.path.join(config.getdefault('pants_workdir'), 'test', task_type.__name__)

    bootstrap_options = OptionsBootstrapper().get_bootstrap_options()

    options = Options(env={}, config=config, known_scopes=['', 'test'], args=args or [])
    # A lot of basic code uses these options, so always register them.
    register_bootstrap_options(options.register_global)

    # We need to wrap register_global (can't set .bootstrap attr on the bound instancemethod).
    def register_global_wrapper(*args, **kwargs):
      return options.register_global(*args, **kwargs)

    register_global_wrapper.bootstrap = bootstrap_options.for_global_scope()
    register_global_options(register_global_wrapper)

    task_type.options_scope = 'test'
    task_type.register_options_on_scope(options)

    run_tracker = create_run_tracker()

    context = Context(config,
                      options,
                      run_tracker,
                      targets or [],
                      build_graph=build_graph,
                      build_file_parser=build_file_parser,
                      address_mapper=address_mapper,
                      console_outstream=console_outstream,
                      workspace=workspace)
    return task_type(context, workdir)

  def targets(self, spec):
    """Resolves a target spec to one or more Target objects.

    spec: Either BUILD target address or else a target glob using the siblings ':' or
          descendants '::' suffixes.

    Returns the set of all Targets found.
    """

    spec_parser = CmdLineSpecParser(self.build_root, self.address_mapper)
    addresses = list(spec_parser.parse_addresses(spec))
    for address in addresses:
      self.build_graph.inject_address_closure(address)
    targets = [self.build_graph.get_target(address) for address in addresses]
    return targets

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

  def setUp(self):
    Goal.clear()
    super(ConsoleTaskTest, self).setUp()

    task_type = self.task_type()
    assert issubclass(task_type, ConsoleTask), \
        'task_type() must return a ConsoleTask subclass, got %s' % task_type

  def execute_task(self, config=None, args=None, targets=None):
    """Creates a new task and executes it with the given config, command line args and targets.

    config:        an optional string representing the contents of a pants.ini config.
    args:          optional list of command line flags, these should be prefixed with '--test-'.
    targets:       optional list of Target objects passed on the command line.
    Returns the text output of the task.
    """
    with closing(StringIO()) as output:
      task = self.prepare_task(config=config,
                               args=args,
                               targets=targets,
                               build_graph=self.build_graph,
                               build_file_parser=self.build_file_parser,
                               address_mapper=self.address_mapper,
                               console_outstream=output)
      task.execute()
      return output.getvalue()

  def execute_console_task(self, config=None, args=None, targets=None, extra_targets=None,
                           workspace=None):
    """Creates a new task and executes it with the given config, command line args and targets.

    config:        an optional string representing the contents of a pants.ini config.
    args:          optional list of command line flags, these should be prefixed with '--test-'.
    targets:       optional list of Target objects passed on the command line.
    extra_targets: optional list of extra targets in the context in addition to those passed on the
                   command line.
    workspace:     optional Workspace to pass into the context.

    Returns the list of items returned from invoking the console task's console_output method.
    """
    task = self.prepare_task(config=config,
                             args=args,
                             targets=targets,
                             build_graph=self.build_graph,
                             build_file_parser=self.build_file_parser,
                             address_mapper=self.address_mapper,
                             workspace=workspace)
    return list(task.console_output(list(task.context.targets()) + list(extra_targets or ())))

  def assert_entries(self, sep, *output, **kwargs):
    """Verifies the expected output text is flushed by the console task under test.

    NB: order of entries is not tested, just presence.

    sep:      the expected output separator.
    *output:  the output entries expected between the separators
    **kwargs: additional kwargs passed to execute_task.
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
    **kwargs: additional kwargs passed to execute_console_task.
    """
    self.assertEqual(sorted(output), sorted(self.execute_console_task(**kwargs)))

  def assert_console_output_ordered(self, *output, **kwargs):
    """Verifies the expected output entries are emitted by the console task under test.

    NB: order of entries is tested.

    *output:  the expected output entries in expected order
    **kwargs: additional kwargs passed to execute_console_task.
    """
    self.assertEqual(list(output), self.execute_console_task(**kwargs))

  def assert_console_raises(self, exception, **kwargs):
    """Verifies the expected exception is raised by the console task under test.

    **kwargs: additional kwargs are passed to execute_console_task.
    """
    with self.assertRaises(exception):
      self.execute_console_task(**kwargs)
