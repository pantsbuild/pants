# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import file_option
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass


class ScalaFmt(NailgunTask, AbstractClass):
  """Abstract class to run ScalaFmt commands.

  Classes that inherit from this should override get_command_args and
  process_results to run different scalafmt commands

  :API: public
  """
  _SCALAFMT_MAIN = 'org.scalafmt.cli.Cli'
  _SCALA_SOURCE_EXTENSION = '.scala'

  @classmethod
  def register_options(cls, register):
    super(ScalaFmt, cls).register_options(register)
    register('--skip', type=bool, fingerprint=False, help='Skip Scalafmt Check')
    register('--configuration', advanced=True, type=file_option, fingerprint=False,
              help='Path to scalafmt config file, if not specified default scalafmt config used')
    register('--target-types',
             default={'scala_library', 'junit_tests', 'java_tests'},
             advanced=True,
             type=set,
             help='The target types to apply formatting to.')
    cls.register_jvm_tool(register,
                          'scalafmt',
                          classpath=[
                          JarDependency(org='com.geirsson',
                                        name='scalafmt-cli_2.11',
                                        rev='0.2.11')
                          ])

  @memoized_property
  def _formatted_target_types(self):
    aliases = self.get_options().target_types
    registered_aliases = self.context.build_file_parser.registered_aliases()
    return tuple({target_type
                  for alias in aliases
                  for target_type in registered_aliases.target_types_by_alias[alias]})

  def execute(self):
    """Runs Scalafmt on all found Scala Source Files."""
    if self.get_options().skip:
      return

    targets = self.get_non_synthetic_scala_targets(self.context.targets())
    sources = self.calculate_sources(targets)

    if sources:
      files = ",".join(sources)

      result = self.runjava(classpath=self.tool_classpath('scalafmt'),
                   main=self._SCALAFMT_MAIN,
                   args=self.get_command_args(files),
                   workunit_name='scalafmt')

      self.process_results(result)

  @abstractproperty
  def get_command_args(self, files):
    """Returns the arguments used to run Scalafmt command.

    The return value should be an array of strings.  For
    example, to run the Scalafmt help command:
    ['--help']
    """

  @abstractproperty
  def process_results(self, result):
    """This method processes the results of the scalafmt command.

    No return value is expected.  If an error occurs running
    Scalafmt raising a TaskError is recommended.
    """

  def get_non_synthetic_scala_targets(self, targets):
    return filter(
      lambda target: isinstance(target, self._formatted_target_types)
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

  If the files are not formatted correctly an error is raised
  including the command to run to format the files correctly

  :API: public
  """
  deprecated_options_scope = 'compile.scalafmt'
  deprecated_options_scope_removal_version = '1.5.0.dev0'

  def get_command_args(self, files):
    # If no config file is specified use default scalafmt config.
    config_file = self.get_options().configuration
    args = ['--test', '--files', files]
    if config_file!= None:
      args.extend(['--config', config_file])

    return args

  def process_results(self, result):
    if result != 0:
      raise TaskError('Scalafmt failed with exit code {}; to fix run: '
                      '`./pants fmt <targets>`'.format(result), exit_code=result)


class ScalaFmtFormat(ScalaFmt):
  """This Task reads all scala files in the target and emits
  the source in a standard style as specified by the configuration
  file.

  This task mutates the underlying flies.

  :API: public
  """

  def get_command_args(self, files):
    # If no config file is specified use default scalafmt config.
    config_file = self.get_options().configuration
    args = ['-i', '--files', files]
    if config_file!= None:
      args.extend(['--config', config_file])

    return args

  def process_results(self, result):
    # Processes the results of running the scalafmt command.
    if result != 0:
      raise TaskError('Scalafmt failed to format files', exit_code=result)
