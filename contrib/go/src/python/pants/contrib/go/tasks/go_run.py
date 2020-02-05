# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.base.deprecated import deprecated_conditional
from pants.base.exceptions import TaskError
from pants.process.xargs import Xargs

from pants.contrib.go.tasks.go_task import GoTask


class GoRun(GoTask):
  """Runs an executable Go binary."""

  @classmethod
  def supports_passthru_args(cls):
    return True

  @classmethod
  def prepare(cls, options, round_manager):
    super().prepare(options, round_manager)
    round_manager.require_data('exec_binary')

  def execute(self):
    deprecated_conditional(
      lambda: self.get_passthru_args(),
      removal_version='1.28.0.dev0',
      entity_description='Using the old style of passthrough args for `run.go`',
      hint_message="You passed arguments to the Go program through either the "
                   "`--run-go-passthrough-args` option or the style "
                   "`./pants run.go -- arg1 --arg2`. Instead, "
                   "pass any arguments to the Go program like this: "
                   "`./pants run --args='arg1 --arg2' src/go/path/to:target`.\n\n"
                   "This change is meant to reduce confusion in how option scopes work with "
                   "passthrough args and for parity with the V2 implementation of the `run` goal.",
    )

    target = self.require_single_root_target()
    if self.is_binary(target):
      binary_path = self.context.products.get_data('exec_binary')[target]
      # TODO(cgibb): Wrap with workunit and stdout/stderr plumbing.
      res = Xargs.subprocess(
        [binary_path]
      ).execute([*self.get_passthru_args(), *self.get_options().args])
      if res != 0:
        raise TaskError(f'{os.path.basename(binary_path)} exited non-zero ({res})')
