# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
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
    # NB: Because we mix the compiler classpath into the scalafix classpath later, we
    # don't shade (ie, specify a `main=`) here.
    # TODO: This is full-versioned, which we don't have great support for in ScalaPlatform.
    cls.register_jvm_tool(register,
                          'scalafix',
                          classpath=[
                            JarDependency(org='ch.epfl.scala', name='scalafix-cli_2.11.8', rev='0.3.3-ASNAPSHOT-mirror-7'),
                            JarDependency(org='org.scalameta', name='scalahost-nsc_2.11.8', rev='1.7.0-485-086c4ac9', classifier='compile'),
                          ])

  @classmethod
  def subsystem_dependencies(cls):
    return super(ScalaFix, cls).subsystem_dependencies() + (ScalaPlatform,)

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

  @memoized_method
  def _complete_tool_classpath(self):
    """Include the compiler with the scalafix classpath."""
    cp = list(ScalaPlatform.global_instance().compiler_classpath(self.context.products))
    cp.extend(self.tool_classpath('scalafix'))
    return cp

  @memoized_method
  def _jvm_options(self):
    """Extends the user provided jvm_options to specify the location of the scalahost jar."""
    opts = list(self.get_options().jvm_options)
    tool_classpath = [cpe for cpe in self.tool_classpath('scalafix')
                      if self._SCALAHOST_NAME in cpe and '-javadoc' not in cpe and '-sources' not in cpe]
    if not len(tool_classpath) == 1:
      raise TaskError('Expected exactly one classpath entry for scalahost: got {} from {}'.format(
        tool_classpath, self.tool_classpath('scalafix')))
    opts.append('-Dscalahost.jar={}'.format(tool_classpath[0]))
    return tuple(opts)

  def _run(self, target, results_dir, classpaths):
    # We operate on copies of the files, so we execute in place.
    args = ['--in-place', '--files={}'.format(results_dir)]
    args.append('--sourcepath={}'.format(results_dir))
    args.append('--classpath={}'.format(
      ':'.join(jar for _, jar in classpaths.get_for_targets(target.closure(bfs=True)))))
    if self.get_options().config:
      args.append('--config={}'.format(self.get_options().config))
    if self.get_options().level == 'debug':
      args.append('--debug')

    # Clone all sources to relative names in their destination directory.
    for source, short_name in zip(target.sources_relative_to_buildroot(),
                                  target.sources_relative_to_target_base()):
      abs_path = os.path.join(get_buildroot(), source)
      dest_file = os.path.join(results_dir, short_name)
      safe_mkdir_for(dest_file)
      shutil.copy(abs_path, dest_file)

    # Execute.
    result = self.runjava(classpath=self._complete_tool_classpath(),
                          main=self._SCALAFIX_MAIN,
                          jvm_options=self._jvm_options(),
                          args=args, workunit_name='scalafix')
    if result != 0:
      raise TaskError(
          'java {main} ... exited non-zero ({result}) for {target}'.format(
            main=self._SCALAFIX_MAIN,
            result=result,
            target=target.address.spec),
          failed_targets=[target])
