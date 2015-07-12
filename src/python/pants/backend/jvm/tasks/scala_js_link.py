# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.scala_js_library import ScalaJSLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.option.options import Options
from pants.util.dirutil import safe_mkdir


class ScalaJSLink(NailgunTask):

  _SCALA_JS_CLI_MAIN = 'org.scalajs.cli.Scalajsld'

  @classmethod
  def register_options(cls, register):
    super(ScalaJSLink, cls).register_options(register)
    register('--opt-full', default=False, action='store_true',
             help='Perform all optimizations; this is generally only useful for deployments.')
    register('--check-ir', default=False, action='store_true', advanced=True,
             help='Perform (relatively costly) validity checks of IR before linking it.')
    register('--jvm-options', action='append', metavar='<option>...', advanced=True,
             help='Run with these extra jvm options.')
    cls.register_jvm_tool(register, 'scala-js-cli', main=cls._SCALA_JS_CLI_MAIN)

  @classmethod
  def prepare(cls, options, round_manager):
    super(ScalaJSLink, cls).prepare(options, round_manager)
    # Require that compilation has completed.
    round_manager.require_data('classes_by_target')
    round_manager.require_data('compile_classpath')

  @classmethod
  def product_types(cls):
    # Outputs are provided as synthetic resource targets to downstream consumers.
    return ['resources_by_target']

  @property
  def cache_target_dirs(self):
    return True

  def _is_linked(self, target):
    return isinstance(target, ScalaJSLibrary)

  def _target_file(self, vt):
    return os.path.join(vt.results_dir, "{}.js".format(vt.target.id))

  def execute(self):
    resources_by_target = self.context.products.get_data('resources_by_target')
    with self.invalidated(self.context.targets(self._is_linked)) as invalidation_check:
      for vt in invalidation_check.all_vts:
        if not vt.valid:
          self._link(vt.target, self._target_file(vt))
        resources_by_target[vt.target].add_abs_paths(vt.results_dir, [self._target_file(vt)])

  def _link(self, target, output_file):
    args = ['--output', output_file]
    if self.get_options().level == 'debug':
      args.append('--debug')
    if self.get_options().opt_full:
      args.append('--fullOpt')
    if self.get_options().check_ir:
      args.append('--checkIR')

    compile_classpaths = self.context.products.get_data('compile_classpath')
    args.extend(jar for _, jar in compile_classpaths.get_for_target(target))

    result = self.runjava(classpath=self.tool_classpath('scala-js-cli'), main=self._SCALA_JS_CLI_MAIN,
                          jvm_options=self.get_options().jvm_options,
                          args=args, workunit_name='scala-js-link')

    if result != 0:
      raise TaskError('java {main} ... exited non-zero ({result})'.format(
        main=self._SCALA_JS_CLI_MAIN, result=result))
