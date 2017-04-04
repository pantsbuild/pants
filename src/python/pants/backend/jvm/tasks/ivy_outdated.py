# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.workunit import WorkUnitLabel
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.java.jar.jar_dependency import JarDependency
from pants.util.memo import memoized_property


class IvyOutdated(NailgunTask):
  """Checks for outdated jar dependencies with Ivy"""

  _IVY_DEPENDENCY_UPDATE_MAIN = 'org.pantsbuild.tools.ivy.DependencyUpdateChecker'

  @classmethod
  def subsystem_dependencies(cls):
    return super(IvyOutdated, cls).subsystem_dependencies() + (IvySubsystem.scoped(cls),)

  @classmethod
  def register_options(cls, register):
    super(IvyOutdated, cls).register_options(register)
    register('--confs', type=list, default=['default'],
             help='Pass a configuration to ivy in addition to the default ones.')
    register('--exclude-patterns', type=list, default=[],
             help='Regular expressions matching jars to be excluded from outdated report.')

    cls.register_jvm_tool(register,
                          'dependency-update-checker',
                          classpath=[
                            JarDependency(org='org.pantsbuild',
                                          name='ivy-dependency-update-checker',
                                          rev='0.0.1'),
                          ],
                          main=cls._IVY_DEPENDENCY_UPDATE_MAIN,
                          custom_rules=[
                            Shader.exclude_package('org.apache.ivy', recursive=True)
                          ]
                          )

  @memoized_property
  def _exclude_patterns(self):
    return [re.compile(x) for x in set(self.get_options().exclude_patterns or [])]

  def _is_update_coordinate(self, coordinate):
    for pattern in self._exclude_patterns:
      if pattern.search(str(coordinate)):
        self.context.log.debug(
          "Skipping [{}] because it matches exclude pattern '{}'".format(coordinate, pattern.pattern))
        return False
    return True

  def execute(self):
    targets = self.context.targets()
    jars, global_excludes = IvyUtils.calculate_classpath(targets)

    filtered_jars = [jar for jar in jars if self._is_update_coordinate(jar.coordinate)]
    sorted_jars = sorted((jar for jar in filtered_jars), key=lambda x: (x.org, x.name, x.rev, x.classifier))

    ivyxml = os.path.join(self.workdir, 'ivy.xml')
    IvyUtils.generate_ivy(targets, jars=sorted_jars, excludes=global_excludes, ivyxml=ivyxml, confs=['default'])

    args = [
      '-settings', IvySubsystem.global_instance().get_options().ivy_settings,
      '-ivy', ivyxml,
      '-confs', ','.join(self.get_options().confs)
    ]

    result = self.runjava(classpath=self.tool_classpath('dependency-update-checker'),
                          main=self._IVY_DEPENDENCY_UPDATE_MAIN,
                          jvm_options=self.get_options().jvm_options,
                          args=args,
                          workunit_name='dependency-update-checker',
                          workunit_labels=[WorkUnitLabel.LINT])

    self.context.log.debug('java {main} ... exited with result ({result})'.format(
      main=self._IVY_DEPENDENCY_UPDATE_MAIN, result=result))

    return result
