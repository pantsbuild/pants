# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import filecmp
import os
import shutil
from abc import abstractmethod

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import file_option
from pants.util.dirutil import safe_mkdir_for
from pants.util.meta import AbstractClass


class ScalaFix(NailgunTask, AbstractClass):
  """Executes the scalafix tool."""

  _SCALAFIX_MAIN = 'scalafix.cli.Cli'
  _SCALA_SOURCE_EXTENSION = '.scala'
  _SCALAHOST_NAME = 'scalahost-nsc'

  cache_target_dirs = True

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
                            JarDependency(org='ch.epfl.scala', name='scalafix-cli_2.11.11', rev='0.4.2'),
                          ])

  @classmethod
  def prepare(cls, options, round_manager):
    super(ScalaFix, cls).prepare(options, round_manager)
    round_manager.require_data('runtime_classpath')

  @abstractmethod
  def _finalize_target(self, target, results_dir):
    """Given a Target and a successfully populated results_dir containing its sources, finalize."""

  def _is_fixed(self, target):
    return target.has_sources(self._SCALA_SOURCE_EXTENSION) and (not target.is_synthetic)

  def execute(self):
    classpaths = self.context.products.get_data('runtime_classpath')
    # NB: This task uses only the literal classpath of each target, so does not need
    # `invalidate_dependents=True`.
    with self.invalidated(self.context.targets(self._is_fixed)) as invalidation_check:
      for vt in invalidation_check.all_vts:
        if not vt.valid:
          self.context.log.debug('Fixing {}...'.format(vt.target.address.spec))
          classpath = [e for _, e in classpaths.get_for_target(vt.target)]
          self._run(vt.target, vt.results_dir, classpath)
        else:
          self.context.log.debug('Already fixed {}'.format(vt.target.address.spec))
        # Target outputs are valid: finalize them.
        self._finalize_target(vt.target, vt.results_dir)

  def _run(self, target, results_dir, classpath):
    # We always operate on copies of the files, so we execute in place.
    args = ['--in-place']
    args.append('--sourceroot={}'.format(results_dir))
    args.append('--classpath={}'.format(':'.join(classpath)))
    if self.get_options().config:
      args.append('--config={}'.format(self.get_options().config))
    if self.get_options().rewrites:
      args.append('--rewrites={}'.format(self.get_options().rewrites))
    if self.get_options().level == 'debug':
      args.append('--verbose')

    # Clone all sources to relative names in their destination directory.
    for rel_source in target.sources_relative_to_buildroot():
      src = os.path.join(get_buildroot(), rel_source)
      dst = os.path.join(results_dir, rel_source)
      safe_mkdir_for(dst)
      shutil.copy(src, dst)

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


class ScalaFixFix(ScalaFix):
  """Applies fixes generated by scalafix."""

  def _finalize_target(self, target, results_dir):
    for rel_source in target.sources_relative_to_buildroot():
      src = os.path.join(results_dir, rel_source)
      dst = os.path.join(get_buildroot(), rel_source)
      shutil.copy(src, dst)


class ScalaFixCheck(ScalaFix):
  """Checks whether any fixes were generated by scalafix."""

  def _finalize_target(self, target, results_dir):
    for rel_source in target.sources_relative_to_buildroot():
      src = os.path.join(results_dir, rel_source)
      dst = os.path.join(get_buildroot(), rel_source)
      # TODO: Should collect all failures rather than bailing immediately.
      if not filecmp.cmp(src, dst, shallow=False):
        raise TaskError('Target requires fixes:\n  {}'.format(target.address.spec))
