# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.option.custom_types import file_option
from pants.util.dirutil import relative_symlink, safe_mkdir_for


class ScalaFix(NailgunTask):
  """Executes the scalafix tool."""

  _SCALAFIX_MAIN = 'scalafix.cli.Cli'
  _SCALA_SOURCE_EXTENSION = '.scala'

  @classmethod
  def register_options(cls, register):
    super(ScalaFix, cls).register_options(register)
    register('--config', type=file_option, default=None, fingerprint=True,
             help='The config file to use (in HOCON format).')
    cls.register_jvm_tool(register,
                          'scalafix',
                          main=cls._SCALAFIX_MAIN,
                          classpath=[
                            ScalaJarDependency(org='ch.epfl.scala', name='scalafix-cli', rev='0.3.2')
                          ])

  @classmethod
  def prepare(cls, options, round_manager):
    super(ScalaFix, cls).prepare(options, round_manager)
    # Require that compilation has completed.
    round_manager.require_data('runtime_classpath')

  @property
  def cache_target_dirs(self):
    return True

  def _is_fixed(self, target):
    return target.has_sources(self._SCALA_SOURCE_EXTENSION) and (not target.is_synthetic)

  def execute(self):
    classpaths = self.context.products.get_data('runtime_classpath')
    with self.invalidated(
        self.context.targets(self._is_fixed),
        invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.all_vts:
        if not vt.valid:
          self.context.log.debug('Fixing {}...'.format(vt.target.address.spec))
          self._run(vt.target, vt.results_dir, classpaths)
        else:
          self.context.log.debug('Already fixed {}'.format(vt.target.address.spec))
        # Target outputs are valid: link them to dist.
        self._link_to_dist(vt)

  def _link_to_dist(self, vt):
    dest_dir = os.path.join(self.get_options().pants_distdir, 'scalafix', vt.target.id)
    safe_mkdir_for(dest_dir)
    relative_symlink(vt.current_results_dir, dest_dir)

  def _run(self, target, results_dir, classpaths):
    # All options aside from the input filename will be the same for a target: create
    # them once and freeze them.
    baseargs = []
    if self.get_options().config:
      baseargs.append('--config={}'.format(self.get_options().config))
    if self.get_options().level == 'debug':
      baseargs.append('--debug')
    baseargs = tuple(baseargs)

    classpath = [jar for _, jar in classpaths.get_for_targets(target.closure(bfs=True))]
    classpath.extend(self.tool_classpath('scalafix'))
    classpath = tuple(classpath)

    for source, short_name in zip(target.sources_relative_to_buildroot(),
                                  target.sources_relative_to_target_base()):
      abs_path = os.path.join(get_buildroot(), source)

      args = baseargs + tuple(['--files={}'.format(abs_path)])
      result = self.runjava(classpath=classpath, main=self._SCALAFIX_MAIN,
                            jvm_options=self.get_options().jvm_options,
                            args=args, workunit_name='scalafix')

      if result != 0:
        raise TaskError(
            'java {main} ... exited non-zero ({result}) for {target} and {source}'.format(
              main=self._SCALA_JS_CLI_MAIN,
              result=result,
              target=target.address.spec,
              source=source),
            failed_targets=[target])

      # FIXME: Need to capture the workunit output and store it in the results_dir: currently
      # just copying the existing file.
      dest_file = os.path.join(results_dir, short_name)
      safe_mkdir_for(dest_file)
      shutil.copy(abs_path, dest_file)
