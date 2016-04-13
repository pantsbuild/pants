# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.goal.products import MultipleRootedProducts

from pants.contrib.scalajs.subsystems.scala_js_platform import ScalaJSPlatform
from pants.contrib.scalajs.targets.scala_js_binary import ScalaJSBinary


class ScalaJSLink(NailgunTask):
  """Links intermediate scala.js representation outputs into a javascript binary."""

  _SCALA_JS_CLI_MAIN = 'org.scalajs.cli.Scalajsld'

  @classmethod
  def register_options(cls, register):
    super(ScalaJSLink, cls).register_options(register)
    register('--full-opt', type=bool, fingerprint=True,
             help='Perform all optimizations; this is generally only useful for deployments.')
    register('--check-ir', type=bool, fingerprint=True,
             help='Perform (relatively costly) validity checks of IR before linking it.')
    # TODO: revisit after https://rbcommons.com/s/twitter/r/3225/
    cls.register_jvm_tool(register, 'scala-js-cli', main=cls._SCALA_JS_CLI_MAIN)

  @classmethod
  def prepare(cls, options, round_manager):
    super(ScalaJSLink, cls).prepare(options, round_manager)
    # Require that scala_js compilation has completed.
    round_manager.require_data('scala_js_ir')

  @classmethod
  def product_types(cls):
    # Outputs are javascript blobs provided as a product or a resource to downstream consumers.
    return ['scala_js_binaries', 'runtime_classpath']

  @classmethod
  def global_subsystems(cls):
    return {ScalaJSPlatform}

  @property
  def cache_target_dirs(self):
    return True

  def _is_linked(self, target):
    return isinstance(target, ScalaJSBinary)

  def _target_file(self, vt):
    return os.path.join(vt.results_dir, "{}.js".format(vt.target.name))

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

  def _link(self, target, output_file, classpaths):
    args = ['--output', output_file]
    if self.get_options().level == 'debug':
      args.append('--debug')
    if self.get_options().full_opt:
      args.append('--fullOpt')
    if self.get_options().check_ir:
      args.append('--checkIR')

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
