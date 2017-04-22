# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.collections import OrderedSet

from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import dict_with_files_option, file_option
from pants.process.xargs import Xargs
from pants.util.dirutil import safe_open


class Checkstyle(NailgunTask):
  """Check Java code for style violations.

  :API: public
  """

  _CHECKSTYLE_MAIN = 'com.puppycrawl.tools.checkstyle.Main'

  _JAVA_SOURCE_EXTENSION = '.java'

  _CHECKSTYLE_BOOTSTRAP_KEY = "checkstyle"

  deprecated_options_scope = 'compile.checkstyle'
  deprecated_options_scope_removal_version = '1.5.0.dev0'

  @classmethod
  def register_options(cls, register):
    super(Checkstyle, cls).register_options(register)
    register('--skip', type=bool, fingerprint=True,
             help='Skip checkstyle.')
    register('--configuration', advanced=True, type=file_option, fingerprint=True,
             help='Path to the checkstyle configuration file.')
    register('--properties', advanced=True, type=dict_with_files_option, default={},
             fingerprint=True,
             help='Dictionary of property mappings to use for checkstyle.properties.')
    register('--confs', advanced=True, type=list, default=['default'],
             help='One or more ivy configurations to resolve for this target.')
    register('--include-user-classpath', type=bool, fingerprint=True,
             help='Add the user classpath to the checkstyle classpath')
    cls.register_jvm_tool(register,
                          'checkstyle',
                          # Note that checkstyle 7.0 does not run on Java 7 runtimes or below.
                          classpath=[
                            JarDependency(org='com.puppycrawl.tools',
                                          name='checkstyle',
                                          rev='6.19'),
                          ],
                          main=cls._CHECKSTYLE_MAIN,
                          custom_rules=[
                              # Checkstyle uses reflection to load checks and has an affordance that
                              # allows leaving off a check classes' package name.  This affordance
                              # breaks for built-in checkstyle checks under shading so we ensure all
                              # checkstyle packages are excluded from shading such that just its
                              # third party transitive deps (guava and the like), are shaded.
                              # See the module configuration rules here which describe this:
                              #   http://checkstyle.sourceforge.net/config.html#Modules
                              Shader.exclude_package('com.puppycrawl.tools.checkstyle',
                                                     recursive=True),
                          ])

  @classmethod
  def prepare(cls, options, round_manager):
    super(Checkstyle, cls).prepare(options, round_manager)
    if options.include_user_classpath:
      round_manager.require_data('runtime_classpath')

  def _is_checked(self, target):
    return target.has_sources(self._JAVA_SOURCE_EXTENSION) and not target.is_synthetic

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    if self.get_options().skip:
      return
    targets = self.context.targets(self._is_checked)
    with self.invalidated(targets) as invalidation_check:
      invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]
      sources = self.calculate_sources(invalid_targets)
      if sources:
        result = self.checkstyle(invalid_targets, sources)
        if result != 0:
          raise TaskError('java {main} ... exited non-zero ({result})'.format(
            main=self._CHECKSTYLE_MAIN, result=result))

  def calculate_sources(self, targets):
    sources = set()
    for target in targets:
      sources.update(source for source in target.sources_relative_to_buildroot()
                     if source.endswith(self._JAVA_SOURCE_EXTENSION))
    return sources

  def checkstyle(self, targets, sources):
    union_classpath = OrderedSet(self.tool_classpath('checkstyle'))
    if self.get_options().include_user_classpath:
      runtime_classpaths = self.context.products.get_data('runtime_classpath')
      for target in targets:
        runtime_classpath = runtime_classpaths.get_for_targets(target.closure(bfs=True))
        union_classpath.update(jar for conf, jar in runtime_classpath
                               if conf in self.get_options().confs)

    configuration_file = self.get_options().configuration
    if not configuration_file:
      raise TaskError('No checkstyle configuration file provided.')

    args = [
      '-c', configuration_file,
      '-f', 'plain'
    ]

    if self.get_options().properties:
      properties_file = os.path.join(self.workdir, 'checkstyle.properties')
      with safe_open(properties_file, 'w') as pf:
        for k, v in self.get_options().properties.items():
          pf.write('{key}={value}\n'.format(key=k, value=v))
      args.extend(['-p', properties_file])

    # We've hit known cases of checkstyle command lines being too long for the system so we guard
    # with Xargs since checkstyle does not accept, for example, @argfile style arguments.
    def call(xargs):
      return self.runjava(classpath=union_classpath, main=self._CHECKSTYLE_MAIN,
                          jvm_options=self.get_options().jvm_options,
                          args=args + xargs, workunit_name='checkstyle')
    checks = Xargs(call)

    return checks.execute(sources)
