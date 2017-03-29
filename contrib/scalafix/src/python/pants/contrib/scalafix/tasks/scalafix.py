# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.goal.products import MultipleRootedProducts


class ScalaFix(NailgunTask):
  """Executes the scalafix tool."""

  _SCALAFIX_MAIN = 'scalafix.cli.Cli'

  @classmethod
  def register_options(cls, register):
    super(ScalaFix, cls).register_options(register)
    register('--full-opt', type=bool, fingerprint=True,
             help='Perform all optimizations; this is generally only useful for deployments.')
    cls.register_jvm_tool(register, 'scalafix', main=cls._SCALA_JS_CLI_MAIN)

  @classmethod
  def prepare(cls, options, round_manager):
    super(ScalaFix, cls).prepare(options, round_manager)
    # Require that compilation has completed.
    round_manager.require_data('runtime_classpath')

  def execute(self):
    scala_js_binaries = self.context.products.get_data('scala_js_binaries',
                                                       lambda: defaultdict(MultipleRootedProducts))
    classpaths = self.context.products.get_data('runtime_classpath')
    with self.invalidated(
        self.context.targets(self._is_linked),
        invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.all_vts:
        if not vt.valid:
          self.context.log.debug('Linking {}...'.format(vt.target.address.spec))
          self._link(vt.target, self._target_file(vt), classpaths)
        else:
          self.context.log.debug('Already linked {}'.format(vt.target.address.spec))
        scala_js_binaries[vt.target].add_abs_paths(vt.results_dir, [self._target_file(vt)])
        classpaths.add_for_target(vt.target, [('default', vt.results_dir)])

  def _run(self, target, classpaths):
    args = []
    if self.get_options().level == 'debug':
      args.append('--debug')

    # NB: We give the linker the entire classpath for this target, and let it check validity.
    args.extend(jar for _, jar in classpaths.get_for_targets(target.closure(bfs=True)))

    result = self.runjava(classpath=self.tool_classpath('scala-js-cli'), main=self._SCALA_JS_CLI_MAIN,
                          jvm_options=self.get_options().jvm_options,
                          args=args, workunit_name='scala-js-link')

    # TODO: scopt doesn't exit(1) when it receives an invalid option, but in all cases here
    # that should be caused by a task-implementation error rather than a user error.
    if result != 0:
      raise TaskError(
          'java {main} ... exited non-zero ({result}) for {target}'.format(
            main=self._SCALA_JS_CLI_MAIN, result=result, target=target.address.spec),
          failed_targets=[target])
    if not os.path.exists(output_file):
      raise TaskError(
          'java {main} ... failed to produce an output for {target}'.format(
            main=self._SCALA_JS_CLI_MAIN, target=target.address.spec),
          failed_targets=[target])
