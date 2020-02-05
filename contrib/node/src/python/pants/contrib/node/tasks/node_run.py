# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import deprecated_conditional
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.util.contextutil import pushd

from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_task import NodeTask


class NodeRun(NodeTask):
  """Runs a script specified in a package.json file, currently through "npm run [script name]"."""

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--script-name', default='start',
             help='The script name to run.')

  @classmethod
  def supports_passthru_args(cls):
    return True

  def execute(self):

    deprecated_conditional(
      lambda: self.get_passthru_args(),
      removal_version='1.28.0.dev0',
      entity_description='Using the old style of passthrough args for `run.node`',
      hint_message="You passed arguments to the Node program through either the "
                   "`--run-node-passthrough-args` option or the style "
                   "`./pants run.node -- arg1 --arg2`. Instead, "
                   "pass any arguments to the Node program like this: "
                   "`./pants run --args='arg1 --arg2' src/javascript/path/to:target`.\n\n"
                   "This change is meant to reduce confusion in how option scopes work with "
                   "passthrough args and for parity with the V2 implementation of the `run` goal.",
    )

    target = self.require_single_root_target()

    if self.is_node_module(target):
      node_paths = self.context.products.get_data(NodePaths)
      with pushd(node_paths.node_path(target)):
        result, command = self.run_script(
          self.get_options().script_name,
          target=target,
          script_args=[*self.get_passthru_args(), *self.get_options().args],
          node_paths=node_paths.all_node_paths,
          workunit_name=target.address.reference(),
          workunit_labels=[WorkUnitLabel.RUN])
        if result != 0:
          raise TaskError('Run script failed:\n'
                          '\t{} failed with exit code {}'.format(command, result))
