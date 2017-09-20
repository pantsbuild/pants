# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty, abstractmethod

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import file_option
from pants.process.xargs import Xargs
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass


class ScalaRewriteBase(NailgunTask, AbstractClass):
  """Abstract base class for both scalafix and scalafmt: tools that check/rewrite scala sources."""

  @classmethod
  def register_options(cls, register):
    super(ScalaRewriteBase, cls).register_options(register)
    register('--skip', type=bool, fingerprint=False, help='Skip Scalafmt Check')
    register('--target-types',
             default=['scala_library', 'junit_tests', 'java_tests'],
             advanced=True,
             type=list,
             help='The target types to apply formatting to.')

  @memoized_property
  def _formatted_target_types(self):
    aliases = set(self.get_options().target_types)
    registered_aliases = self.context.build_file_parser.registered_aliases()
    return tuple({target_type
                  for alias in aliases
                  for target_type in registered_aliases.target_types_by_alias[alias]})

  @property
  def cache_target_dirs(self):
    return not self.sideeffecting

  def execute(self):
    """Runs the tool on all Scala source files that are located."""
    if self.get_options().skip:
      return

    targets = self.get_non_synthetic_scala_targets(self.context.targets())

    if self.sideeffecting:
      # Always execute sideeffecting tasks without invalidation.
      self._execute_for(targets)
    else:
      # If the task is not sideeffecting we can use invalidation.
      with self.invalidated(targets) as invalidation_check:
        self._execute_for([vt.target for vt in invalidation_check.invalid_vts])

  def _execute_for(self, targets):
    sources = self.calculate_sources(targets)
    if not sources:
      return

    command = self._invoke_tool_in_place if self.in_place else self._invoke_tool_with_tempdir
    result = Xargs(command).execute(sources)
    if result != 0:
      # Both _invoke_tool_in_place and _invoke_tool_with_tempdir raise exceptions eagerly.
      raise TaskError('{} is improperly implemented: a failed process '
                      'should raise an exception earlier.'.format(type(self).__name__))

  def _invoke_tool_with_tempdir(self, sources_relative_to_buildroot):
    # Clone all sources to relative names in a temporary directory.
    with temporary_dir() as tmpdir:
      mapping = {}
      for rel_source in sources_relative_to_buildroot:
        src = os.path.join(get_buildroot(), rel_source)
        dst = os.path.join(tmpdir, rel_source)
        safe_mkdir_for(dst)
        shutil.copy(src, dst)
        mapping[src] = dst
      result = self.invoke_tool(sources_relative_to_buildroot)
      self.process_results(mapping, result)
      return result

  def _invoke_tool_in_place(self, sources_relative_to_buildroot):
    # Invoke in place.
    mapping = {s: s for s in sources_relative_to_buildroot}
    result = self.invoke_tool(sources_relative_to_buildroot)
    self.process_results(mapping, result)
    return result

  @abstractmethod
  def invoke_tool(self, sources_relative_to_buildroot):
    """Invoke the tool on the given sources.

    Should return the UNIX return code of the tool.
    """

  @abstractproperty
  def in_place(self):
    """Returns True if the command should run on files directly in the source tree.

    If False, files will first be cloned to a temporary directory.
    """

  @abstractproperty
  def sideeffecting(self):
    """Returns True if this command has sideeffects: ie, mutates the working copy."""

  @abstractmethod
  def get_command_args(self, files):
    """Returns the arguments used to run Scalafmt command.

    The return value should be an array of strings.  For
    example, to run the Scalafmt help command:
    ['--help']
    """

  @abstractmethod
  def process_results(self, input_output_mapping, return_code):
    """Given a mapping from input to output file and a return code, process the result of the tool.

    No return value is expected. If an error occurred while running the tool, raising a TaskError
    is recommended.

    If `in_place=True`, the input/output mapping will map files to themselves.
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
