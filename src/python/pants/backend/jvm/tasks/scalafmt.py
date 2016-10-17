# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.build_graph.target import Target
from pants.option.custom_types import file_option


class ScalaFmt(NailgunTask):
  """ScalaFmt base class executes the help command.  
  
  Classes that inherit from this should override get_command_args and
  process_results to run different scalafmt commands

  :API: public
  """
  _SCALAFMT_MAIN = 'org.scalafmt.cli.Cli'
  _SCALA_SOURCE_EXTENSION = '.scala'

  @classmethod
  def register_options(cls, register):
    super(ScalaFmt, cls).register_options(register)
    register('--skip', type=bool, fingerprint=True, help='Skip Scalafmt Check')
    register('--configuration', advanced=True, type=file_option, fingerprint=True,
              help='Path to scalafmt config file, if not specified default scalafmt config used')
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
      files = ",".join(sources)

      config_file = self.get_options().configuration
      result = self.runjava(classpath=self.tool_classpath('scalafmt'),
                   main=self._SCALAFMT_MAIN,
                   args=self.get_command_args(config_file, files),
                   workunit_name='scalafmt')

      self.process_results(result)

  def get_command_args(self, config_file, files):
    """Gets the arguments for running Scalafmt
    
    Base class just runs help command
    """
    return ['--help']

  def process_results(self, result):
    if result != 0:
      raise TaskError('Failed to run Scalafmt', exit_code=result)

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


class ScalaFmtCheckFormat(ScalaFmt):
  """This Task checks that all scala files in the target are formatted
  correctly.  

  If the files are not formatted correctly are not an error is raised 
  including the command to run to format the files correctly

  :API: public
  """

  def get_command_args(self, config_file, files):
    # If no config file is specified use default scalafmt config.
    args = ['--test', '--files', files]
    if config_file != None:
      args.extend(['--config', config_file])

    return args

  def process_results(self, result):
    # Processes the results of running the scalafmt command.
    if result != 0:
      raise TaskError('Scalafmt failed with exit code {} to fix run: `./pants fmt <targets>`'.format(result), exit_code=result)


class ScalaFmtFormat(ScalaFmt):
  """This Task formats all scala files in the targets.

  :API: public
  """

  def get_command_args(self, config_file, files):
    # If no config file is specified use default scalafmt config.
    args = ['-i', '--files', files]
    if config_file != None:
      args.extend(['--config', config_file])

    return args

  def process_results(self, result):
    # Processes the results of running the scalafmt command.
    if result != 0:
      raise TaskError('Scalafmt failed to format files', exit_code=result)

