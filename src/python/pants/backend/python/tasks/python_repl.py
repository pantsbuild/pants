# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pex.pex import PEX

from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.target import Target
from pants.base.workunit import WorkUnit
from pants.console import stty_utils
from pants.option.options import Options


class PythonRepl(PythonTask):
  @classmethod
  def register_options(cls, register):
    super(PythonRepl, cls).register_options(register)
    register('--ipython', action='store_true',
             help='Run an IPython REPL instead of the standard python one.')
    register('--ipython-entry-point', advanced=True, default='IPython:start_ipython',
             help='The IPython REPL entry point.')
    register('--ipython-requirements', advanced=True, type=Options.list, default=['ipython==1.0.0'],
             help='The IPython interpreter version to use.')

  # NB: **pex_run_kwargs is used by tests only, execute nominally has (void)void signature.
  def execute(self, **pex_run_kwargs):
    (accept_predicate, reject_predicate) = Target.lang_discriminator('python')
    targets = self.require_homogeneous_targets(accept_predicate, reject_predicate)
    if targets:
      # We can't throw if the target isn't a python target, because perhaps we were called on a
      # JVM target, in which case we have to no-op and let scala repl do its thing.
      # TODO(benjy): Some more elegant way to coordinate how tasks claim targets.
      interpreter = self.select_interpreter_for_targets(targets)

      extra_requirements = []
      if self.get_options().ipython:
        entry_point = self.get_options().ipython_entry_point
        for req in self.get_options().ipython_requirements:
          extra_requirements.append(PythonRequirement(req))
      else:
        entry_point = 'code:interact'

      with self.temporary_pex_builder(interpreter=interpreter) as builder:
        builder.set_entry_point(entry_point)
        chroot = PythonChroot(
          context=self.context,
          targets=targets,
          extra_requirements=extra_requirements,
          builder=builder,
          interpreter=interpreter)

        chroot.dump()
        builder.freeze()
        pex = PEX(builder.path(), interpreter=interpreter)
        self.context.release_lock()
        with stty_utils.preserve_stty_settings():
          with self.context.new_workunit(name='run', labels=[WorkUnit.RUN]):
            po = pex.run(blocking=False, **pex_run_kwargs)
            try:
              return po.wait()
            except KeyboardInterrupt:
              pass
