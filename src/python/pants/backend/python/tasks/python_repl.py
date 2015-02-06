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


class PythonRepl(PythonTask):
  @classmethod
  def register_options(cls, register):
    super(PythonRepl, cls).register_options(register)
    register('--ipython', action='store_true',
             help='Run an IPython REPL instead of the standard python one.')

  def execute(self):
    (accept_predicate, reject_predicate) = Target.lang_discriminator('python')
    targets = self.require_homogeneous_targets(accept_predicate, reject_predicate)
    if targets:
      # We can't throw if the target isn't a python target, because perhaps we were called on a
      # JVM target, in which case we have to no-op and let scala repl do its thing.
      # TODO(benjy): Some more elegant way to coordinate how tasks claim targets.
      interpreter = self.select_interpreter_for_targets(targets)

      extra_requirements = []
      if self.get_options().ipython:
        entry_point = self.context.config.get('python-ipython', 'entry_point',
                                              default='IPython:start_ipython')
        ipython_requirements = self.context.config.getlist('python-ipython', 'requirements',
                                                           default=['ipython==1.0.0'])
        for req in ipython_requirements:
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
            po = pex.run(blocking=False)
            try:
              return po.wait()
            except KeyboardInterrupt:
              pass
