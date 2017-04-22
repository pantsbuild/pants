# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.backend.jvm.subsystems.shader import Shader, Shading
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.java.jar.jar_dependency import JarDependency
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property
from pants.util.strutil import safe_shlex_split


class ErrorProne(NailgunTask):
  """Check Java code for Error Prone violations.  See http://errorprone.info/ for more details."""

  _ERRORPRONE_MAIN = 'com.google.errorprone.ErrorProneCompiler'
  _JAVA_SOURCE_EXTENSION = '.java'

  @classmethod
  def register_options(cls, register):
    super(ErrorProne, cls).register_options(register)

    register('--skip', type=bool, help='Skip Error Prone.')
    register('--transitive', default=False, type=bool,
             help='Run Error Prone against transitive dependencies of targets '
                  'specified on the command line.')
    register('--command-line-options', type=list, default=[], fingerprint=True,
             help='Command line options passed to Error Prone')
    register('--exclude-patterns', type=list, default=[], fingerprint=True,
             help='Patterns for targets to be excluded from analysis.')

    cls.register_jvm_tool(register,
                          'errorprone',
                          classpath=[
                            JarDependency(org='com.google.errorprone',
                                          name='error_prone_core',
                                          rev='2.0.17'),
                          ],
                          main=cls._ERRORPRONE_MAIN,
                          custom_rules=[
                            Shader.exclude_package('com.google.errorprone', recursive=True),
                            Shading.create_exclude('*'), # https://github.com/pantsbuild/pants/issues/4288
                          ]
                         )

  @classmethod
  def prepare(cls, options, round_manager):
    super(ErrorProne, cls).prepare(options, round_manager)
    round_manager.require_data('runtime_classpath')

  @memoized_property
  def _exclude_patterns(self):
    return [re.compile(x) for x in set(self.get_options().exclude_patterns or [])]

  def _is_errorprone_target(self, target):
    if not target.has_sources(self._JAVA_SOURCE_EXTENSION):
      self.context.log.debug('Skipping [{}] because it has no {} sources'.format(target.address.spec, self._JAVA_SOURCE_EXTENSION))
      return False
    if target.is_synthetic:
      self.context.log.debug('Skipping [{}] because it is a synthetic target'.format(target.address.spec))
      return False
    for pattern in self._exclude_patterns:
      if pattern.search(target.address.spec):
        self.context.log.debug(
          "Skipping [{}] because it matches exclude pattern '{}'".format(target.address.spec, pattern.pattern))
        return False
    return True

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    if self.get_options().skip:
      return

    if self.get_options().transitive:
      targets = self.context.targets(self._is_errorprone_target)
    else:
      targets = filter(self._is_errorprone_target, self.context.target_roots)

    targets = list(set(targets))

    target_count = 0
    errorprone_failed = False
    with self.invalidated(targets, invalidate_dependents=True) as invalidation_check:
      total_targets = len(invalidation_check.invalid_vts)
      for vt in invalidation_check.invalid_vts:
        target_count += 1
        self.context.log.info('[{}/{}] {}'.format(
          str(target_count).rjust(len(str(total_targets))),
          total_targets,
          vt.target.address.spec))

        result = self.errorprone(vt.target)
        if result != 0:
          errorprone_failed = True
          if self.get_options().fail_fast:
            break
        else:
          vt.update()

      if errorprone_failed:
        raise TaskError('ErrorProne checks failed')

  def calculate_sources(self, target):
    return {source for source in target.sources_relative_to_buildroot()
            if source.endswith(self._JAVA_SOURCE_EXTENSION)}

  def errorprone(self, target):
    runtime_classpaths = self.context.products.get_data('runtime_classpath')
    runtime_classpath = [jar for conf, jar in runtime_classpaths.get_for_targets(target.closure(bfs=True))]

    output_dir = os.path.join(self.workdir, target.id)
    safe_mkdir(output_dir)
    runtime_classpath.append(output_dir)

    args = [
      '-classpath', ':'.join(runtime_classpath),
      '-d', output_dir,
    ]

    for opt in self.get_options().command_line_options:
      args.extend(safe_shlex_split(opt))

    args.extend(self.calculate_sources(target))

    result = self.runjava(classpath=self.tool_classpath('errorprone'),
                          main=self._ERRORPRONE_MAIN,
                          jvm_options=self.get_options().jvm_options,
                          args=args,
                          workunit_name='errorprone',
                          workunit_labels=[WorkUnitLabel.LINT])

    self.context.log.debug('java {main} ... exited with result ({result})'.format(
                           main=self._ERRORPRONE_MAIN, result=result))

    return result
