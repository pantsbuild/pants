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

  @classmethod
  def supports_passthru_args(cls):
    return True

  def _run_node_distribution_command(self, command, workunit, **kwargs):
    return self._spawn_and_wait(command, workunit, **kwargs)

  def _execute(self, all_targets):
    targets = self._get_test_targets()
    if not targets:
      return

    node_paths = self.context.products.get_data(NodePaths)

    for target in targets:
      for dep in target.dependencies:
        node_path = node_paths.node_path(dep)

        args = ['run', target.script_name] + self.get_passthru_args()

        with pushd(node_path):
          # If the _spawn_and_wait invoked by execute_npm times out, it raises a TestFailedTaskError
          # with failed_targets set to self._get_test_targets() (i.e., all test targets for this
          # _execute call), even though we are actually executing it for each target individually.
          # This seems alright though since we are letting the exception bubble up and break this
          # whole _execute.
          result, npm_test_command = self.execute_npm(args=args,
                                                      workunit_labels=[WorkUnitLabel.TEST])
          if result != 0:
            raise TaskError('npm test script failed:\n'
                            '\t{} failed with exit code {}'.format(npm_test_command, result))

  def _spawn(self, command, workunit, **kwargs):
    process = command.run(stdout=workunit.output('stdout'),
                          stderr=workunit.output('stderr'),
                          **kwargs)
    return SubprocessProcessHandler(process)

  def _test_target_filter(self):
    return self.is_node_test

  def _validate_target(self, target):
    for dep in target.dependencies:
      if not self.is_node_module(dep):
        raise TargetDefinitionException(target,
                                        'NodeTest targets can only depend on node module targets.')
