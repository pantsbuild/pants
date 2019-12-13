# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from abc import abstractmethod
from typing import List

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.tasks.rewrite_base import RewriteBase
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.binaries.binary_tool import NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.engine.platform import Platform
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import file_option
from pants.process.xargs import Xargs
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.lint_task_mixin import LintTaskMixin
from pants.util.dirutil import chmod_plus_x
from pants.util.memo import memoized_method


class ScalaFmtNativeUrlGenerator(BinaryToolUrlGenerator):

  _DIST_URL_FMT = 'https://github.com/scalameta/scalafmt/releases/download/v{version}/scalafmt-{system_id}.zip'

  _SYSTEM_ID = {
    'mac': 'macos',
    'linux': 'linux',
  }

  def generate_urls(self, version, host_platform):
    system_id = self._SYSTEM_ID[host_platform.os_name]
    return [self._DIST_URL_FMT.format(version=version, system_id=system_id)]


class ScalaFmtSubsystem(JvmToolMixin, NativeTool):
  options_scope = 'scalafmt'
  default_version = '2.3.1'
  archive_type = 'zip'

  def get_external_url_generator(self):
    return ScalaFmtNativeUrlGenerator()

  @memoized_method
  def select(self):
    """Reach into the unzipped directory and return the scalafmt executable.

    Also make sure to chmod +x the scalafmt executable, since the release zip doesn't do that.
    """
    extracted_dir = super().select()
    inner_dir_name = Platform.current.match({
      Platform.darwin: 'scalafmt-macos',
      Platform.linux: 'scalafmt-linux',
    })
    output_file = os.path.join(extracted_dir, inner_dir_name, 'scalafmt')
    chmod_plus_x(output_file)
    return output_file

  @property
  def use_native_image(self) -> bool:
    return bool(self.get_options().use_native_image)

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--use-native-image', type=bool, advanced=True, fingerprint=False,
             help='Use a pre-compiled native-image for scalafmt.')

    cls.register_jvm_tool(register,
                          'scalafmt',
                          classpath=[
                          JarDependency(org='com.geirsson',
                                        name='scalafmt-cli_2.11',
                                        rev='1.5.1')])


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
  def register_options(cls, register):
    super().register_options(register)
    register('--configuration', advanced=True, type=file_option, fingerprint=True,
              help='Path to scalafmt config file, if not specified default scalafmt config used')

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
    config_file = self.get_options().configuration
    prefix_args = list(self.additional_args)
    if config_file is not None:
      prefix_args.extend(['--config', config_file])

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
