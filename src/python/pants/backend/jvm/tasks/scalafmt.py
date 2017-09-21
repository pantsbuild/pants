# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty

from pants.backend.jvm.tasks.scala_rewrite_base import ScalaRewriteBase
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import file_option


class ScalaFmt(ScalaRewriteBase):
  """Abstract class to run ScalaFmt commands.

  Classes that inherit from this should override get_command_args and
  process_results to run different scalafmt commands.
  """
  _SCALAFMT_MAIN = 'org.scalafmt.cli.Cli'
  _SCALA_SOURCE_EXTENSION = '.scala'

  @classmethod
  def register_options(cls, register):
    super(ScalaFmt, cls).register_options(register)
    register('--configuration', advanced=True, type=file_option, fingerprint=True,
              help='Path to scalafmt config file, if not specified default scalafmt config used')
    cls.register_jvm_tool(register,
                          'scalafmt',
                          classpath=[
                          JarDependency(org='com.geirsson',
                                        name='scalafmt-cli_2.11',
                                        rev='1.0.0-RC4')
                          ])

  @classmethod
  def implementation_version(cls):
    return super(ScalaFmt, cls).implementation_version() + [('ScalaFmt', 5)]

  def invoke_tool(self, sources):
    files = ",".join(sources)

    return self.runjava(classpath=self.tool_classpath('scalafmt'),
                        main=self._SCALAFMT_MAIN,
                        args=self.get_command_args(files),
                        workunit_name='scalafmt',
                        jvm_options=self.get_options().jvm_options)

  @abstractproperty
  def get_command_args(self, files):
    """Returns the arguments used to run Scalafmt command.

    The return value should be an array of strings.  For
    example, to run the Scalafmt help command:
    ['--help']
    """


class ScalaFmtCheckFormat(ScalaFmt):
  """This Task checks that all scala files in the target are formatted
  correctly.

  If the files are not formatted correctly an error is raised
  including the command to run to format the files correctly

  :API: public
  """
  deprecated_options_scope = 'compile.scalafmt'
  deprecated_options_scope_removal_version = '1.5.0.dev0'

  in_place = True
  sideeffecting = False

  def get_command_args(self, files):
    # If no config file is specified use default scalafmt config.
    config_file = self.get_options().configuration
    args = ['--test', '--files', files]
    if config_file != None:
      args.extend(['--config', config_file])

    return args

  def process_results(self, _, result):
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

  in_place = True
  sideeffecting = True

  def get_command_args(self, files):
    # If no config file is specified use default scalafmt config.
    config_file = self.get_options().configuration
    args = ['-i', '--files', files]
    if config_file != None:
      args.extend(['--config', config_file])

    return args

  def process_results(self, _, result):
    # Processes the results of running the scalafmt command.
    if result != 0:
      raise TaskError('Scalafmt failed to format files', exit_code=result)
