# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re

from pants.backend.jvm import argfile
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.revision import Revision
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
    super().register_options(register)

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
                                          rev='2.3.1'),
                          ],
                          main=cls._ERRORPRONE_MAIN,
                          custom_rules=[
                            Shader.exclude_package('com.google.errorprone', recursive=True)
                          ]
                         )

    # The javac version should be kept in sync with the version used by errorprone above.
    cls.register_jvm_tool(register,
                          'errorprone-javac',
                          classpath=[
                            JarDependency(org='com.google.errorprone',
                                          name='javac',
                                          rev='9+181-r4173-1'),
                          ])

  @classmethod
  def prepare(cls, options, round_manager):
    super().prepare(options, round_manager)
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
      targets = [t for t in self.context.target_roots if self._is_errorprone_target(t)]

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

    # Try to run errorprone with the same java version as the target
    # The minimum JDK for errorprone is JDK 1.8
    min_jdk_version = max(target.platform.target_level, Revision.lenient('1.8'))
    if min_jdk_version.components[0] == 1:
      max_jdk_version = Revision(min_jdk_version.components[0], min_jdk_version.components[1], '9999')
    else:
      max_jdk_version = Revision(min_jdk_version.components[0], '9999')
    self.set_distribution(minimum_version=min_jdk_version, maximum_version=max_jdk_version, jdk=True)

    jvm_options = self.get_options().jvm_options[:]
    if self.dist.version < Revision.lenient('9'):
      # For Java 8 we need to add the errorprone javac jar to the bootclasspath to
      # avoid the "java.lang.NoSuchFieldError: ANNOTATION_PROCESSOR_MODULE_PATH" error
      # See https://github.com/google/error-prone/issues/653 for more information
      jvm_options.extend(['-Xbootclasspath/p:{}'.format(self.tool_classpath('errorprone-javac')[0])])

    args = [
      '-d', output_dir,
    ]

    # Errorprone does not recognize source or target 10 yet
    if target.platform.source_level < Revision.lenient('10'):
      args.extend(['-source', str(target.platform.source_level)])

    if target.platform.target_level < Revision.lenient('10'):
      args.extend(['-target', str(target.platform.target_level)])

    errorprone_classpath_file = os.path.join(self.workdir, '{}.classpath'.format(os.path.basename(output_dir)))
    with open(errorprone_classpath_file, 'w') as f:
      f.write('-classpath ')
      f.write(':'.join(runtime_classpath))
    args.append('@{}'.format(errorprone_classpath_file))

    for opt in self.get_options().command_line_options:
      args.extend(safe_shlex_split(opt))

    with argfile.safe_args(self.calculate_sources(target), self.get_options()) as batched_sources:
      args.extend(batched_sources)
      result = self.runjava(classpath=self.tool_classpath('errorprone'),
                            main=self._ERRORPRONE_MAIN,
                            jvm_options=jvm_options,
                            args=args,
                            workunit_name='errorprone',
                            workunit_labels=[WorkUnitLabel.LINT])

      self.context.log.debug('java {main} ... exited with result ({result})'.format(
        main=self._ERRORPRONE_MAIN, result=result))

    return result
