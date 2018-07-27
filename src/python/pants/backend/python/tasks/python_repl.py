# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import signal

from pex.pex_info import PexInfo

from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.python_execution_task_base import PythonExecutionTaskBase
from pants.task.repl_task_mixin import ReplTaskMixin
from pants.util.contextutil import signal_handler_as


class PythonRepl(ReplTaskMixin, PythonExecutionTaskBase):
  """Launch an interactive Python interpreter session."""

  @classmethod
  def register_options(cls, register):
    super(PythonRepl, cls).register_options(register)
    # TODO: Create a python equivalent of register_jvm_tool, and use that instead of these
    # ad-hoc options.
    register('--ipython', type=bool,
             help='Run an IPython REPL instead of the standard python one.')
    register('--ipython-entry-point', advanced=True, default='IPython:start_ipython',
             help='The IPython REPL entry point.')
    register('--ipython-requirements', advanced=True, type=list, default=['ipython==1.0.0'],
             help='The IPython interpreter version to use.')
    register('--compatibility', advanced=True, type=list, default=[],
             help='Add constraints to the interpreter version to use.')

  @classmethod
  def select_targets(cls, target):
    return isinstance(target, (PythonTarget, PythonRequirementLibrary))

  def extra_requirements(self):
    if self.get_options().ipython:
      return self.get_options().ipython_requirements
    else:
      return []
  
  def merge_interpreter_constraints(self, targets):
    repl_constraints = self.get_options().compatibility
    target_constraints = [constraint for target in targets for constraint in target.compatibility]
    if repl_constraints and target_constraints:
      interpreter_constraints = [",".join(pair) for pair in zip(target_constraints, repl_constraints)]
    else:
      python_setup = PythonSetup.global_instance()
      setup_constraints = python_setup.interpreter_constraints
      interpreter_constraints = [",".join(pair) for pair in zip(setup_constraints, repl_constraints)]
    return interpreter_constraints

  def setup_repl_session(self, targets):
    if self.get_options().ipython:
      entry_point = self.get_options().ipython_entry_point
    else:
      entry_point = 'code:interact'
    if self.get_options().compatibility:
      interpreter_constraints = self.get_options().compatibility
    else:
      interpreter_constraints =  [
        constraint for target in targets for constraint in target.compatibility
      ]
    pex_info = PexInfo.default()
    pex_info.entry_point = entry_point
    for constraint in interpreter_constraints:
      pex_info.add_interpreter_constraint(constraint)
    return self.create_pex(pex_info)

  # N.B. **pex_run_kwargs is used by tests only.
  def launch_repl(self, pex, **pex_run_kwargs):
    # While the repl subprocess is synchronously spawned, we rely on process group
    # signalling for a SIGINT to reach the repl subprocess directly - and want to
    # do nothing in response on the parent side.
    def ignore_control_c(signum, frame): pass

    with signal_handler_as(signal.SIGINT, ignore_control_c):
      env = pex_run_kwargs.pop('env', os.environ).copy()
      pex.run(env=env, **pex_run_kwargs)
