# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess
from abc import abstractmethod
from typing import List

from pants.backend.jvm.subsystems.scalafmt import ScalaFmtSubsystem
from pants.backend.jvm.tasks.rewrite_base import RewriteBase
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.process.xargs import Xargs
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.lint_task_mixin import LintTaskMixin


class ScalaFmt(RewriteBase):
  """Abstract class to run ScalaFmt commands.

  Classes that inherit from this should override additional_args and
  process_result to run different scalafmt commands.
  """

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._all_command_lines = []

  @classmethod
  def subsystem_dependencies(cls):
    return super().subsystem_dependencies() + (
      ScalaFmtSubsystem.scoped(cls),
    )

  @classmethod
  def target_types(cls):
    return ['scala_library', 'junit_tests']

  @classmethod
  def source_extension(cls):
    return '.scala'

  @classmethod
  def implementation_version(cls):
    return super().implementation_version() + [('ScalaFmt', 5)]

  @property
  def _use_native_image(self) -> bool:
    return ScalaFmtSubsystem.scoped_instance(self).use_native_image

  def _native_image_path(self) -> str:
    return ScalaFmtSubsystem.scoped_instance(self).select()

  def _tool_classpath(self) -> List[str]:
    subsystem = ScalaFmtSubsystem.scoped_instance(self)
    return subsystem.tool_classpath_from_products(
      self.context.products,
      key='scalafmt',
      scope=subsystem.options_scope)

  def _invoke_native_image_subprocess(self, prefix_args, workunit, all_source_paths):
    self._all_command_lines.append((prefix_args, all_source_paths))
    return subprocess.run(
      args=(prefix_args + all_source_paths),
      stdout=workunit.output('stdout'),
      stderr=workunit.output('stderr'),
    ).returncode

  def _invoke_jvm_process(self, prefix_args, all_source_paths):
    return self.runjava(classpath=self._tool_classpath(),
                        main='org.scalafmt.cli.Cli',
                        args=(prefix_args + all_source_paths),
                        workunit_name='scalafmt',
                        jvm_options=self.get_options().jvm_options)

  def invoke_tool(self, current_workunit, absolute_root, target_sources):
    self.context.log.debug(f'scalafmt called with sources: {target_sources}')

    # If no config file is specified, use default scalafmt config.
    config_file = ScalaFmtSubsystem.scoped_instance(self).configuration
    prefix_args = list(self.additional_args)
    if config_file is not None:
      prefix_args.extend(['--config', str(config_file)])

    all_source_paths = [source for _target, source in target_sources]

    if self._use_native_image:
      with self.context.run_tracker.new_workunit(
          name='scalafmt',
          labels=[WorkUnitLabel.COMPILER],
      ) as workunit:
        prefix_args = [self._native_image_path()] + prefix_args
        self.context.log.debug(f'executing scalafmt with native image with prefix args: {prefix_args}')
        return Xargs(
          self._invoke_native_image_subprocess,
          constant_args=[prefix_args, workunit],
        ).execute(all_source_paths)
    else:
      return Xargs(self._invoke_jvm_process, constant_args=[prefix_args]).execute(all_source_paths)

  @property
  @abstractmethod
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
