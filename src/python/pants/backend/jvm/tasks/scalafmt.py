# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.build_graph.target import Target
from pants.option.custom_types import file_option


class ScalaFmt(NailgunTask):
  """Checks Scala code matches scalafmt style.

  :API: public
  """
  _SCALAFMT_MAIN = 'org.scalafmt.cli.Cli'
  _SCALA_SOURCE_EXTENSION = '.scala'

  @classmethod
  def register_options(cls, register):
    super(ScalaFmt, cls).register_options(register)
    register('--skip', type=bool, fingerprint=True, help='Skip Scalafmt Check')
    register('--configuration', advanced=True, type=file_option, fingerprint=True,
              help='Path to scalafmt config file.')
    cls.register_jvm_tool(register,
                          'scalafmt',
                          classpath=[
                          JarDependency(org='com.geirsson',
                                        name='scalafmt-cli_2.11',
                                        rev='0.2.11')
                          ])

  def execute(self):
    """Runs Scalafmt on all found Scala Source Files."""
    if self.get_options().skip:
      return

    targets = self.get_non_synthetic_scala_targets(self.context.targets())
    sources = self.calculate_sources(targets)

    if sources:
      files = ""
      for source in sources:
        files = files + source + ','

      configFile = self.get_options().configuration
      args = ['--test', '--config', configFile, '--files', files]

      result = self.runjava(classpath=self.tool_classpath('scalafmt'),
                   main=self._SCALAFMT_MAIN,
                   args=args,
                   workunit_name='scalafmt')

      if result != 0:
        scalafmtCmd = 'scalafmt -i --config {} --files {}'.format(configFile, files)
        raise TaskError('Scalafmt failed with exit code {} to fix run: `{}`'.format(result, scalafmtCmd), exit_code=result)
  
  def get_non_synthetic_scala_targets(self, targets):
    return filter(
      lambda target: isinstance(target, Target)
                     and target.has_sources(self._SCALA_SOURCE_EXTENSION)
                     and (not target.is_synthetic),
      targets)

  def calculate_sources(self, targets):
    sources = set() 
    for target in targets:
      sources.update(source for source in target.sources_relative_to_buildroot()
                      if source.endswith(self._SCALA_SOURCE_EXTENSION))
    return sources
