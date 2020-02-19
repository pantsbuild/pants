# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.pex_info import PexInfo

from pants.backend.python.subsystems.ipython import IPython
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.python_execution_task_base import PythonExecutionTaskBase
from pants.base.deprecated import resolve_conflicting_options
from pants.base.exception_sink import ExceptionSink
from pants.task.repl_task_mixin import ReplTaskMixin


class PythonRepl(ReplTaskMixin, PythonExecutionTaskBase):
  """Launch an interactive Python interpreter session."""

  def _resolve_conflicting_options(self, *, old_option: str, new_option: str):
    return resolve_conflicting_options(
      old_option=old_option,
      new_option=new_option,
      old_scope="repl-py",
      new_scope="ipython",
      old_container=self.get_options(),
      new_container=IPython.global_instance().options,
    )

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      "--ipython",
      type=bool,
      fingerprint=True,
      help="Run an IPython REPL instead of the standard python one.",
    )
    register(
      "--ipython-entry-point",
      advanced=True,
      default="IPython:start_ipython",
      removal_version="1.27.0.dev0",
      removal_hint="Use `--ipython-entry-point` instead of `--repl-py-ipython-entry-point`.",
      fingerprint=True,
      help="The IPython REPL entry point.",
    )
    register(
      "--ipython-requirements",
      advanced=True,
      type=list,
      default=["ipython==5.8.0"],
      removal_version="1.27.0.dev0",
      removal_hint="Use `--ipython-version` and `--ipython-extra-requirements` instead of "
      "`--repl-py-ipython-requirements`.",
      fingerprint=True,
      help="The IPython interpreter version to use.",
    )

  @classmethod
  def subsystem_dependencies(cls):
    return super().subsystem_dependencies() + (IPython,)

  @classmethod
  def select_targets(cls, target):
    return isinstance(target, (PythonTarget, PythonRequirementLibrary))

  def extra_requirements(self):
    if not self.get_options().ipython:
      return []
    ipython_version = self._resolve_conflicting_options(
      old_option="ipython_requirements", new_option="version"
    )
    ipython_extra_requirements = self._resolve_conflicting_options(
      old_option="ipython_requirements", new_option="extra_requirements"
    )
    if isinstance(ipython_version, list):
      return self.get_options().ipython_requirements
    return [ipython_version, *ipython_extra_requirements]

  def setup_repl_session(self, targets):
    if self.get_options().ipython:
      entry_point = self._resolve_conflicting_options(
        old_option="ipython_entry_point", new_option="entry_point"
      )
    else:
      entry_point = "code:interact"
    pex_info = PexInfo.default()
    pex_info.entry_point = entry_point
    return self.create_pex(pex_info)

  def _run_repl(self, pex, **pex_run_kwargs):
    env = self.prepare_pex_env(env=pex_run_kwargs.pop("env", None))
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
