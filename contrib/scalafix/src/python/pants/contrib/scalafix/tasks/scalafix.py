# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import file_option
from pants.util.dirutil import relative_symlink, safe_mkdir_for
from pants.util.memo import memoized_method


class ScalaFix(NailgunTask):
  """Executes the scalafix tool."""

  _SCALAFIX_MAIN = 'scalafix.cli.Cli'
  _SCALA_SOURCE_EXTENSION = '.scala'
  _SCALAHOST_NAME = 'scalahost-nsc'

  @classmethod
  def register_options(cls, register):
    super(ScalaFix, cls).register_options(register)
    register('--config', type=file_option, default=None, fingerprint=True,
             help='The config file to use (in HOCON format).')
    register('--rewrites', default=None, fingerprint=True,
             help='The `rewrites` arg to scalafix: generally a name like `ProcedureSyntax`.')
    cls.register_jvm_tool(register,
                          'scalafix',
                          classpath=[
                            JarDependency(org='ch.epfl.scala', name='scalafix-cli_2.11.11', rev='0.4.0'),
                          ])

  @classmethod
  def subsystem_dependencies(cls):
    return super(ScalaFix, cls).subsystem_dependencies() + (ScalaPlatform,)

  @classmethod
  def implementation_version(cls):
    return super(ScalaFix, cls).implementation_version() + [('ScalaFix', 1)]

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
    safe_mkdir_for(dest_dir, clean=True)
    relative_symlink(vt.current_results_dir, dest_dir)

  def _run(self, target, results_dir, classpaths):
    # We operate on copies of the files, so we execute in place.
    args = ['--in-place']
    # FIXME: This argument is not used currently, meaning that files are implicitly
    # fixed in the buildroot itself. Once this issue is fixed, we should copy back
    # out of the results_dir to the final location on success.
    #  see https://github.com/scalacenter/scalafix/issues/176
    args.append('--sourceroot={}'.format(results_dir))
    # NB: Only the classpath of the target itself is necessary:
    #  see https://github.com/scalacenter/scalafix/issues/177
    args.append('--classpath={}'.format(
      ':'.join(jar for _, jar in classpaths.get_for_targets([target]))))
    if self.get_options().config:
      args.append('--config={}'.format(self.get_options().config))
    if self.get_options().rewrites:
      args.append('--rewrites={}'.format(self.get_options().rewrites))
    if self.get_options().level == 'debug':
      args.append('--verbose')

    # Clone all sources to relative names in their destination directory.
    for source in target.sources_relative_to_buildroot():
      abs_path = os.path.join(get_buildroot(), source)
      dest_file = os.path.join(results_dir, source)
      safe_mkdir_for(dest_file)
      shutil.copy(abs_path, dest_file)

    # Execute.
    result = self.runjava(classpath=self.tool_classpath('scalafix'),
                          main=self._SCALAFIX_MAIN,
                          jvm_options=self.get_options().jvm_options,
                          args=args, workunit_name='scalafix')
    if result != 0:
      raise TaskError(
          'java {main} ... exited non-zero ({result}) for {target}'.format(
            main=self._SCALAFIX_MAIN,
            result=result,
            target=target.address.spec),
          failed_targets=[target])
