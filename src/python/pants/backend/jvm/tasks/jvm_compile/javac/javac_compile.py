# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
from builtins import str

from future.utils import text_type

from pants.backend.jvm import argfile
from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.javac_plugin import JavacPlugin
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.engine.fs import DirectoryToMaterialize
from pants.engine.isolated_process import ExecuteProcessRequest
from pants.java.distribution.distribution import DistributionLocator
from pants.util.dirutil import safe_open
from pants.util.process_handler import subprocess


# Well known metadata file to register javac plugins.
_JAVAC_PLUGIN_INFO_FILE = 'META-INF/services/com.sun.source.util.Plugin'

# Well known metadata file to register annotation processors with a java 1.6+ compiler.
_PROCESSOR_INFO_FILE = 'META-INF/services/javax.annotation.processing.Processor'

logger = logging.getLogger(__name__)


class JavacCompile(JvmCompile):
  """Compile Java code using Javac."""

  _name = 'java'
  compiler_name = 'javac'

  @staticmethod
  def _write_javac_plugin_info(resources_dir, javac_plugin_target):
    javac_plugin_info_file = os.path.join(resources_dir, _JAVAC_PLUGIN_INFO_FILE)
    with safe_open(javac_plugin_info_file, 'w') as f:
      f.write(javac_plugin_target.classname)

  @classmethod
  def get_args_default(cls, bootstrap_option_values):
    return ('-encoding', 'UTF-8')

  @classmethod
  def get_warning_args_default(cls):
    return ('-deprecation', '-Xlint:all', '-Xlint:-serial', '-Xlint:-path')

  @classmethod
  def get_no_warning_args_default(cls):
    return ('-nowarn', '-Xlint:none', )

  @classmethod
  def get_fatal_warnings_enabled_args_default(cls):
    return ('-Werror',)

  @classmethod
  def get_fatal_warnings_disabled_args_default(cls):
    return ()

  @classmethod
  def register_options(cls, register):
    super(JavacCompile, cls).register_options(register)

  @classmethod
  def subsystem_dependencies(cls):
    return super(JavacCompile, cls).subsystem_dependencies() + (JvmPlatform,)

  @classmethod
  def prepare(cls, options, round_manager):
    super(JavacCompile, cls).prepare(options, round_manager)

  @classmethod
  def product_types(cls):
    return ['runtime_classpath']

  def __init__(self, *args, **kwargs):
    super(JavacCompile, self).__init__(*args, **kwargs)
    self.set_distribution(jdk=True)

  def select(self, target):
    if not isinstance(target, JvmTarget):
      return False
    return target.has_sources('.java')

  def select_source(self, source_file_path):
    return source_file_path.endswith('.java')

  def javac_classpath(self):
    # Note that if this classpath is empty then Javac will automatically use the javac from
    # the JDK it was invoked with.
    return Java.global_javac_classpath(self.context.products)

  def write_extra_resources(self, compile_context):
    """Override write_extra_resources to produce plugin and annotation processor files."""
    target = compile_context.target
    if isinstance(target, JavacPlugin):
      self._write_javac_plugin_info(compile_context.classes_dir.path, target)
    elif isinstance(target, AnnotationProcessor) and target.processors:
      processor_info_file = os.path.join(compile_context.classes_dir.path, _PROCESSOR_INFO_FILE)
      self._write_processor_info(processor_info_file, target.processors)

  def _write_processor_info(self, processor_info_file, processors):
    with safe_open(processor_info_file, 'w') as f:
      for processor in processors:
        f.write('{}\n'.format(processor.strip()))

  def compile(self, ctx, args, dependency_classpath, upstream_analysis,
              settings, fatal_warnings, zinc_file_manager,
              javac_plugin_map, scalac_plugin_map):
    classpath = (ctx.classes_dir.path,) + tuple(ce.path for ce in dependency_classpath)

    if self.get_options().capture_classpath:
      self._record_compile_classpath(classpath, ctx.target, ctx.classes_dir.path)

    try:
      distribution = JvmPlatform.preferred_jvm_distribution([settings], strict=True)
    except DistributionLocator.Error:
      distribution = JvmPlatform.preferred_jvm_distribution([settings], strict=False)

    javac_cmd = ['{}/bin/javac'.format(distribution.real_home)]

    javac_cmd.extend([
      '-classpath', ':'.join(classpath),
    ])

    if settings.args:
      settings_args = settings.args
      if any('$JAVA_HOME' in a for a in settings.args):
        logger.debug('Substituting "$JAVA_HOME" with "{}" in jvm-platform args.'
                     .format(distribution.home))
        settings_args = (a.replace('$JAVA_HOME', distribution.home) for a in settings.args)
      javac_cmd.extend(settings_args)

      javac_cmd.extend([
        # TODO: support -release
        '-source', str(settings.source_level),
        '-target', str(settings.target_level),
      ])

    if self.execution_strategy == self.HERMETIC:
      javac_cmd.extend([
        # We need to strip the source root from our output files. Outputting to a directory, and
        # capturing that directory, does the job.
        # Unfortunately, javac errors if the directory you pass to -d doesn't exist, and we don't
        # have a convenient way of making a directory in the output tree, so let's just use the
        # working directory as our output dir.
        # This also has the benefit of not needing to strip leading directories from the returned
        # snapshot.
        '-d', '.',
      ])
    else:
      javac_cmd.extend([
        '-d', ctx.classes_dir.path,
      ])

    javac_cmd.extend(self._javac_plugin_args(javac_plugin_map))

    javac_cmd.extend(args)

    if fatal_warnings:
      javac_cmd.extend(self.get_options().fatal_warnings_enabled_args)
    else:
      javac_cmd.extend(self.get_options().fatal_warnings_disabled_args)

    with argfile.safe_args(ctx.sources, self.get_options()) as batched_sources:
      javac_cmd.extend(batched_sources)

      if self.execution_strategy == self.HERMETIC:
        self._execute_hermetic_compile(javac_cmd, ctx)
      else:
        with self.context.new_workunit(name='javac',
                                       cmd=' '.join(javac_cmd),
                                       labels=[WorkUnitLabel.COMPILER]) as workunit:
          self.context.log.debug('Executing {}'.format(' '.join(javac_cmd)))
          p = subprocess.Popen(javac_cmd, stdout=workunit.output('stdout'), stderr=workunit.output('stderr'))
          return_code = p.wait()
          workunit.set_outcome(WorkUnit.FAILURE if return_code else WorkUnit.SUCCESS)
          if return_code:
            raise TaskError('javac exited with return code {rc}'.format(rc=return_code))

  @classmethod
  def _javac_plugin_args(cls, javac_plugin_map):
    ret = []
    for plugin, args in javac_plugin_map.items():
      for arg in args:
        if ' ' in arg:
          # Note: Args are separated by spaces, and there is no way to escape embedded spaces, as
          # javac's Main does a simple split on these strings.
          raise TaskError('javac plugin args must not contain spaces '
                          '(arg {} for plugin {})'.format(arg, plugin))
      ret.append('-Xplugin:{} {}'.format(plugin, ' '.join(args)))
    return ret

  def _execute_hermetic_compile(self, cmd, ctx):
    # For now, executing a compile remotely only works for targets that
    # do not have any dependencies or inner classes

    input_snapshot = ctx.target.sources_snapshot(scheduler=self.context._scheduler)
    output_files = tuple(
      # Assume no extra .class files to grab. We'll fix up that case soon.
      # Drop the source_root from the file path.
      # Assumes `-d .` has been put in the command.
      os.path.relpath(f.path.replace('.java', '.class'), ctx.target.target_base)
      for f in input_snapshot.files if f.path.endswith('.java')
    )
    exec_process_request = ExecuteProcessRequest(
      argv=tuple(cmd),
      input_files=input_snapshot.directory_digest,
      output_files=output_files,
      description='Compiling {} with javac'.format(ctx.target.address.spec),
    )
    exec_result = self.context.execute_process_synchronously_without_raising(
      exec_process_request,
      'javac',
      (WorkUnitLabel.TASK, WorkUnitLabel.JVM),
    )

    # Dump the output to the .pants.d directory where it's expected by downstream tasks.
    classes_directory = ctx.classes_dir.path
    self.context._scheduler.materialize_directories((
      DirectoryToMaterialize(text_type(classes_directory), exec_result.output_directory_digest),
    ))
