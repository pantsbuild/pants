# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from abc import abstractmethod, abstractproperty

from future.utils import text_type

from pants.backend.jvm.subsystems.graal import (BuildNativeImage, CompiledNativeImage, GraalCE,
                                                NativeImageBuildRequest)
from pants.backend.jvm.tasks.rewrite_base import RewriteBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.engine.fs import DirectoryToMaterialize, PathGlobs, PathGlobsAndRoot
from pants.engine.isolated_process import ExecuteProcessRequest
from pants.engine.selectors import Params
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import file_option
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.lint_task_mixin import LintTaskMixin
from pants.util.memo import memoized_property


class ScalaFmt(RewriteBase):
  """Abstract class to run ScalaFmt commands.

  Classes that inherit from this should override additional_args and
  process_result to run different scalafmt commands.
  """

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--configuration', advanced=True, type=file_option, fingerprint=True,
             help='Path to scalafmt config file, if not specified default scalafmt config used')
    register('--use-hermetic-execution', advanced=True, type=bool, default=False,
             help='Execute scalafmt using the v2 engine process execution framework.')
    register('--use-hermetic-native-image', advanced=True, type=bool, default=False,
             help='Use a Graal native-image to execute scalafmt in the v2 engine.')

    cls.register_jvm_tool(register,
                          'scalafmt',
                          classpath=[
                          JarDependency(org='com.geirsson',
                                        name='scalafmt-cli_2.11',
                                        rev='1.5.1')
                          ])

  @classmethod
  def subsystem_dependencies(cls):
    return super(ScalaFmt, cls).subsystem_dependencies() + (
      BuildNativeImage.scoped(cls),
      GraalCE.scoped(cls),
    )

  @classmethod
  def target_types(cls):
    return ['scala_library', 'junit_tests', 'java_tests']

  @classmethod
  def source_extension(cls):
    return '.scala'

  @classmethod
  def implementation_version(cls):
    return super().implementation_version() + [('ScalaFmt', 5)]

  @memoized_property
  def _native_image_build_request(self):
    """Delay the initialization of the scalafmt class which makes relative paths absolute.

    By default with native-image, if provided relative paths to source files, scalafmt will read
    from the 'user.dir' property active at image build time, as native-image executes static
    initializers by default. This behavior can be delayed to runtime, but also tends to require
    searching for other classes which depend on a run-time value and marking them for delayed
    initialization as well: see
    https://medium.com/graalvm/understanding-class-initialization-in-graalvm-native-image-generation-d765b7e4d6ed.

    Here, we ensure that the System.getProperty("user.dir") access is delayed to runtime, which
    allows passing in relative file paths to scalafmt. This allows it to be executed hermetically.
    """
    return NativeImageBuildRequest(
      tool_classpath_snapshot=self.tool_classpath_snapshot('scalafmt'),
      main_class='org.scalafmt.cli.Cli',
      extra_args=tuple([
        '--delay-class-initialization-to-runtime=org.scalafmt.util.AbsoluteFile$',
        '--delay-class-initialization-to-runtime=org.scalafmt.cli.CommonOptions$',
        '--delay-class-initialization-to-runtime=org.scalafmt.cli.CliOptions$',
        '--delay-class-initialization-to-runtime=org.scalafmt.cli.Cli$',
        '--delay-class-initialization-to-runtime=org.scalafmt.util.GitOps$',
      ]),
    )

  @memoized_property
  def _native_image_build_environment(self):
    return GraalCE.scoped_instance(self).create_native_image_build_environment(self.context)

  @memoized_property
  def _scalafmt_built_native_image(self):
    with self.context.new_workunit('build-native-image') as workunit:
      compiled_native_image, = self.context._scheduler.product_request(CompiledNativeImage, tuple([
        Params(
          # TODO: we shouldn't need to do this! the optionable_rule() appears to not be working?!
          BuildNativeImage.scoped_instance(self),
          self._native_image_build_environment,
          self._native_image_build_request),
      ]))
      workunit.output('stdout').write(compiled_native_image.stdout)
      workunit.output('stderr').write(compiled_native_image.stderr)
      return compiled_native_image

  def _execute_hermetic(self, targets):
    if self.get_options().use_hermetic_native_image:
      native_image = self._scalafmt_built_native_image
      base_argv = ['./{}'.format(native_image.file_path)]
      build_env_digest = native_image.built_image
    else:
      classpath_snapshot = self.tool_classpath_snapshot('scalafmt')
      base_argv = [
        self.hermetic_dist.java,
        '-classpath', os.pathsep.join(classpath_snapshot.files + classpath_snapshot.dirs),
        'org.scalafmt.cli.Cli',
      ]
      build_env_digest = classpath_snapshot.directory_digest

    source_snapshots = [
      tgt.sources_snapshot(scheduler=self.context._scheduler)
      for tgt in targets
    ]

    config_file = self.get_options().configuration
    if config_file is not None:
      config_rel_path = os.path.relpath(config_file, get_buildroot())
      merged_snapshot = self.context._scheduler.capture_merged_snapshot(tuple([
        PathGlobsAndRoot(
          PathGlobs([config_rel_path]),
          root=text_type(get_buildroot()),
        )
      ]))
      config_args = ['--config', config_rel_path]
    else:
      merged_snapshot = None
      config_args = []

    merged_inputs = self.context._scheduler.merge_directories(tuple(
      [build_env_digest]
      + [snap.directory_digest for snap in source_snapshots]
      + ([merged_snapshot.directory_digest] if merged_snapshot else [])))
    rel_src_files = [
      src_file
      for snap in source_snapshots
      for src_file in snap.files
    ]

    full_argv = (base_argv
                 + config_args
                 + self.additional_args
                 + rel_src_files)
    request = ExecuteProcessRequest(
      argv=tuple(full_argv),
      input_files=merged_inputs,
      description='execute scalafmt via native-image',
      output_files=tuple(rel_src_files),
      # TODO: this argument could potentially be added automatically.
      jdk_home=self.hermetic_dist.underlying_home
    )
    result = self.context.execute_process_synchronously_without_raising(
      request,
      'execute-scalafmt-hermetically',
    )
    if self.sideeffecting:
      output_dir = self.get_options().output_dir or get_buildroot()
      self.context._scheduler.materialize_directories(tuple([
        DirectoryToMaterialize(
          path=text_type(output_dir),
          directory_digest=result.output_directory_digest,
        ),
        ]))
    return self.process_result(result.exit_code)

  def _execute_for(self, targets):
    if self.get_options().use_hermetic_execution:
      return self._execute_hermetic(targets)
    else:
      return super(ScalaFmt, self)._execute_for(targets)

  def invoke_tool(self, absolute_root, target_sources):
    # If no config file is specified use default scalafmt config.
    config_file = self.get_options().configuration
    args = list(self.additional_args)
    if config_file is not None:
      args.extend(['--config', config_file])
    args.extend([source for _target, source in target_sources])

    return self.runjava(classpath=self.tool_classpath('scalafmt'),
                        main='org.scalafmt.cli.Cli',
                        args=args,
                        workunit_name='scalafmt',
                        jvm_options=self.get_options().jvm_options)

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
