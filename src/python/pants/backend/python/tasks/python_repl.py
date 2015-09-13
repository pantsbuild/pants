# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pex.pex_info import PexInfo

from pants.backend.core.tasks.repl_task_mixin import ReplTaskMixin
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.python_task import PythonTask
from pants.option.custom_types import list_option


class PythonRepl(ReplTaskMixin, PythonTask):
  @classmethod
  def register_options(cls, register):
    super(PythonRepl, cls).register_options(register)
    register('--ipython', action='store_true',
             help='Run an IPython REPL instead of the standard python one.')
    register('--ipython-entry-point', advanced=True, default='IPython:start_ipython',
             help='The IPython REPL entry point.')
    register('--ipython-requirements', advanced=True, type=list_option, default=['ipython==1.0.0'],
             help='The IPython interpreter version to use.')

  @classmethod
  def select_targets(cls, target):
    return isinstance(target, (PythonTarget, PythonRequirementLibrary))

  def setup_repl_session(self, targets):
    interpreter = self.select_interpreter_for_targets(targets)

    extra_requirements = []
    if self.get_options().ipython:
      entry_point = self.get_options().ipython_entry_point
      for req in self.get_options().ipython_requirements:
        extra_requirements.append(PythonRequirement(req))
    else:
      entry_point = 'code:interact'

    pex_info = PexInfo.default()
    pex_info.entry_point = entry_point
    chroot = self.cached_chroot(interpreter=interpreter,
                                pex_info=pex_info,
                                targets=targets,
                                platforms=None,
                                extra_requirements=extra_requirements)
    return chroot.pex()

  # NB: **pex_run_kwargs is used by tests only.
  def launch_repl(self, pex, **pex_run_kwargs):
    po = pex.run(blocking=False, **pex_run_kwargs)
    po.wait()
