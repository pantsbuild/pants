# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.pex_info import PexInfo

from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.python_execution_task_base import PythonExecutionTaskBase
from pants.base.exception_sink import ExceptionSink
from pants.task.repl_task_mixin import ReplTaskMixin


class PythonRepl(ReplTaskMixin, PythonExecutionTaskBase):
  """Launch an interactive Python interpreter session."""

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    # TODO: Create a python equivalent of register_jvm_tool, and use that instead of these
    # ad-hoc options.
    register('--ipython', type=bool,
             help='Run an IPython REPL instead of the standard python one.')
    register('--ipython-entry-point', advanced=True, default='IPython:start_ipython',
             help='The IPython REPL entry point.')
    register('--ipython-requirements', advanced=True, type=list, default=['ipython==1.0.0'],
             help='The IPython interpreter version to use.')

  @classmethod
  def select_targets(cls, target):
    return isinstance(target, (PythonTarget, PythonRequirementLibrary))

  def extra_requirements(self):
    if self.get_options().ipython:
      return self.get_options().ipython_requirements
    else:
      return []

  def setup_repl_session(self, targets):
    if self.get_options().ipython:
      entry_point = self.get_options().ipython_entry_point
    else:
      entry_point = 'code:interact'
    pex_info = PexInfo.default()
    pex_info.entry_point = entry_point
    return self.create_pex(pex_info)

  def _run_repl(self, pex, **pex_run_kwargs):
    env = self.prepare_pex_env(env=pex_run_kwargs.pop('env', None))
    pex.run(env=env, **pex_run_kwargs)

  # N.B. **pex_run_kwargs is used by tests only.
  def launch_repl(self, pex, **pex_run_kwargs):
    # While the repl subprocess is synchronously spawned, we rely on process group
    # signalling for a SIGINT to reach the repl subprocess directly - and want to
    # do nothing in response on the parent side.
    #
    # NB: We use ExceptionSink.ignoring_sigint instead of ExceptionSink.trapped_signals here
    # because this code may be running from a non-main thread when run under pantsd, and therefore
    # will crash if we try to install new signal handlers.
    with ExceptionSink.ignoring_sigint():
      self._run_repl(pex, **pex_run_kwargs)
