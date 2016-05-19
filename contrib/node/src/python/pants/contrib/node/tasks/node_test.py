# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.base.workunit import WorkUnitLabel
from pants.task.testrunner_task_mixin import TestRunnerTaskMixin
from pants.util.contextutil import pushd
from pants.util.process_handler import SubprocessProcessHandler

from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_task import NodeTask


class NodeTest(TestRunnerTaskMixin, NodeTask):
  """Runs a test script from package.json in a NodeModule, currently via "npm run [script name]".

  Implementations of abstract methods from TestRunnerTaskMixin:
  _execute, _spawn, _test_target_filter, _validate_target
  """

  def __init__(self, *args, **kwargs):
    super(NodeTest, self).__init__(*args, **kwargs)
    self._currently_executing_test_targets = []

  @classmethod
  def prepare(cls, options, round_manager):
    super(NodeTest, cls).prepare(options, round_manager)
    round_manager.require_data(NodePaths)

  @classmethod
  def supports_passthru_args(cls):
    return True

  def _run_node_distribution_command(self, command, workunit):
    """Overrides NodeTask._run_node_distribution_command.

    This is what execute_npm ultimately uses to run the NodeDistribution.Command.
    It must return the return code of the process. The base implementation just calls
    command.run immediately. We override here to invoke TestRunnerTaskMixin._spawn_and_wait,
    which ultimately invokes _spawn, which finally calls command.run.
    """
    return self._spawn_and_wait(command, workunit)

  def _get_test_targets_for_spawn(self):
    """Overrides TestRunnerTaskMixin._get_test_targets_for_spawn.

    TestRunnerTaskMixin._spawn_and_wait uses this method to know what targets are being run.
    By default it returns all test targets - here we override it with the list
    self._currently_executing_test_targets, which _execute sets.
    """
    return self._currently_executing_test_targets

  def _execute(self, all_targets):
    """Implements abstract TestRunnerTaskMixin._execute."""
    targets = self._get_test_targets()
    if not targets:
      return

    node_paths = self.context.products.get_data(NodePaths)

    for target in targets:
      node_path = node_paths.node_path(target.dependencies[0])

      args = ['run-script', target.script_name, '--'] + self.get_passthru_args()

      with pushd(node_path):
        self._currently_executing_test_targets = [target]
        result, npm_test_command = self.execute_npm(args, workunit_labels=[WorkUnitLabel.TEST])
        if result != 0:
          raise TaskError('npm test script failed:\n'
                          '\t{} failed with exit code {}'.format(npm_test_command, result))

    self._currently_executing_test_targets = []

  def _spawn(self, command, workunit):
    """Implements abstract TestRunnerTaskMixin._spawn."""
    process = command.run(stdout=workunit.output('stdout'),
                          stderr=workunit.output('stderr'))
    return SubprocessProcessHandler(process)

  def _test_target_filter(self):
    """Implements abstract TestRunnerTaskMixin._test_target_filter."""
    return self.is_node_test

  def _validate_target(self, target):
    """Implements abstract TestRunnerTaskMixin._validate_target."""
    if len(target.dependencies) != 1 or not self.is_node_module(target.dependencies[0]):
      message = 'NodeTest targets must depend on exactly one NodeModule target.'
      raise TargetDefinitionException(target, message)
