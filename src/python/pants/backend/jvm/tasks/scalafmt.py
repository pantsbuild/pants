# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os.path
from abc import abstractproperty

from pants.backend.jvm.tasks.rewrite_base import RewriteBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import dir_option, file_option
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.lint_task_mixin import LintTaskMixin
from pants.util.dirutil import fast_relpath


class ScalaFmt(RewriteBase):
  """Abstract class to run ScalaFmt commands.

  Classes that inherit from this should override additional_args and
  process_result to run different scalafmt commands.
  """

  @classmethod
  def register_options(cls, register):
    super(ScalaFmt, cls).register_options(register)
    register('--configuration', advanced=True, type=file_option, fingerprint=True,
              help='Path to scalafmt config file, if not specified default scalafmt config used')
    # TODO rename flag
    register('--output-dir', advanced=True, type=dir_option, fingerprint=True,
              help='Path to scalafmt output directory. Any updated files will be written here. '
                   'If not specified, files will be modified in-place')

    cls.register_jvm_tool(register,
                          'scalafmt',
                          classpath=[
                          JarDependency(org='com.geirsson',
                                        name='scalafmt-cli_2.11',
                                        rev='1.0.0-RC4')
                          ])

  @classmethod
  def target_types(cls):
    return ['scala_library', 'junit_tests', 'java_tests']

  @classmethod
  def source_extension(cls):
    return '.scala'

  @classmethod
  def implementation_version(cls):
    return super(ScalaFmt, cls).implementation_version() + [('ScalaFmt', 5)]

  def invoke_tool(self, _, target_sources):
    # If no config file is specified use default scalafmt config.
    config_file = self.get_options().configuration
    args = list(self.additional_args)
    if config_file is not None:
      args.extend(['--config', config_file])
    if self.get_options().output_dir:
      args.append('--stdout')

    result = 0
    created_dirs = set()

    for _, source in target_sources:
      res, workunit = self.runjava(classpath=self.tool_classpath('scalafmt'),
                                   main='org.scalafmt.cli.Cli',
                                   args=args + ['--files', source],
                                   workunit_name='scalafmt',
                                   jvm_options=self.get_options().jvm_options,
                                   return_workunit=True)
      result |= res

      if self.get_options().output_dir is not None:
        with open(workunit.output_paths()['stdout'], 'r') as f:
          formatted_file = f.read()

        with open(source, 'r') as f:
          unformatted_file = f.read()

        if formatted_file != unformatted_file:
          path = os.path.join(
            self.get_options().output_dir,
            fast_relpath(source, get_buildroot())
          )

          dir_to_create = os.path.dirname(path)

          if dir_to_create not in created_dirs:
            os.makedirs(os.path.dirname(path))
            created_dirs.add(dir_to_create)

          with open(path, 'w') as f:
            f.write(formatted_file)

    return result

  @abstractproperty
  def additional_args(self):
    """Returns the arguments used to run Scalafmt command.

    The return value should be an array of strings.  For
    example, to run the Scalafmt help command:
    ['--help']
    """


class ScalaFmtCheckFormat(LintTaskMixin, ScalaFmt):
  """This Task checks that all scala files in the target are formatted
  correctly.

  If the files are not formatted correctly an error is raised
  including the command to run to format the files correctly

  :API: public
  """

  sideeffecting = False
  additional_args = ['--test']

  def process_result(self, result):
    if result != 0:
      raise TaskError('Scalafmt failed with exit code {}; to fix run: '
                      '`./pants fmt <targets>`'.format(result), exit_code=result)


class ScalaFmtFormat(FmtTaskMixin, ScalaFmt):
  """This Task reads all scala files in the target and emits
  the source in a standard style as specified by the configuration
  file.

  This task mutates the underlying flies.

  :API: public
  """

  sideeffecting = True
  additional_args = ['-i']

  def process_result(self, result):
    # Processes the results of running the scalafmt command.
    if result != 0:
      raise TaskError('Scalafmt failed to format files', exit_code=result)
