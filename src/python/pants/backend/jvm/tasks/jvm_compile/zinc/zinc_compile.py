# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import textwrap
from contextlib import closing
from xml.etree import ElementTree

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.scalac_plugin import ScalacPlugin
from pants.backend.jvm.tasks.jvm_compile.analysis_tools import AnalysisTools
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_analysis import ZincAnalysis
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_analysis_parser import ZincAnalysisParser
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.hash_utils import hash_file
from pants.base.workunit import WorkUnitLabel
from pants.java.distribution.distribution import DistributionLocator
from pants.option.custom_types import dict_option
from pants.util.contextutil import open_zip
from pants.util.dirutil import safe_open


# Well known metadata file required to register scalac plugins with nsc.
_PLUGIN_INFO_FILE = 'scalac-plugin.xml'


# Well known metadata file to register annotation processors with a java 1.6+ compiler
_PROCESSOR_INFO_FILE = 'META-INF/services/javax.annotation.processing.Processor'


class ZincCompile(JvmCompile):
  """Compile Scala and Java code using Zinc."""

  _ZINC_MAIN = 'org.pantsbuild.zinc.Main'

  _name = 'zinc'

  _supports_concurrent_execution = True

  @staticmethod
  def write_plugin_info(resources_dir, target):
    root = os.path.join(resources_dir, target.id)
    plugin_info_file = os.path.join(root, _PLUGIN_INFO_FILE)
    with safe_open(plugin_info_file, 'w') as f:
      f.write(textwrap.dedent("""
        <plugin>
          <name>{}</name>
          <classname>{}</classname>
        </plugin>
      """.format(target.plugin, target.classname)).strip())
    return root, plugin_info_file

  @staticmethod
  def validate_arguments(log, whitelisted_args, args):
    """Validate that all arguments match whitelisted regexes."""
    valid_patterns = {re.compile(p): v for p, v in whitelisted_args.items()}

    def validate(arg_index):
      arg = args[arg_index]
      for pattern, has_argument in valid_patterns.items():
        if pattern.match(arg):
          return 2 if has_argument else 1
      log.warn("Zinc argument '{}' is not supported, and is subject to change/removal!".format(arg))
      return 1

    arg_index = 0
    while arg_index < len(args):
      arg_index += validate(arg_index)

  @classmethod
  def subsystem_dependencies(cls):
    return super(ZincCompile, cls).subsystem_dependencies() + (ScalaPlatform, DistributionLocator)

  @property
  def compiler_plugin_types(cls):
    """A tuple of target types which are compiler plugins."""
    return (AnnotationProcessor, ScalacPlugin)

  @classmethod
  def get_args_default(cls, bootstrap_option_values):
    return ('-S-encoding', '-SUTF-8', '-S-g:vars')

  @classmethod
  def get_warning_args_default(cls):
    return ('-S-deprecation', '-S-unchecked')

  @classmethod
  def get_no_warning_args_default(cls):
    return ('-S-nowarn',)

  @classmethod
  def register_options(cls, register):
    super(ZincCompile, cls).register_options(register)
    register('--scalac-plugins', advanced=True, action='append', fingerprint=True,
             help='Use these scalac plugins.')
    register('--scalac-plugin-args', advanced=True, type=dict_option, default={}, fingerprint=True,
             help='Map from plugin name to list of arguments for that plugin.')
    # TODO: disable by default because it breaks dependency parsing:
    #   https://github.com/pantsbuild/pants/issues/2224
    # ...also, as of sbt 0.13.9, it is significantly slower for cold builds.
    register('--name-hashing', advanced=True, action='store_true', default=False, fingerprint=True,
             help='Use zinc name hashing.')
    register('--whitelisted-args', advanced=True, type=dict_option,
             default={
               '-S.*': False,
               '-C.*': False,
               '-file-filter': True,
               '-msg-filter': True,
               },
             help='A dict of option regexes that make up pants\' supported API for zinc. '
                  'Options not listed here are subject to change/removal. The value of the dict '
                  'indicates that an option accepts an argument.')

    register('--incremental', advanced=True, action='store_true', default=True,
             help='When set, zinc will use sub-target incremental compilation, which dramatically '
                  'improves compile performance while changing large targets. When unset, '
                  'changed targets will be compiled with an empty output directory, as if after '
                  'running clean-all.')

    # TODO: Defaulting to false due to a few upstream issues for which we haven't pulled down fixes:
    #  https://github.com/sbt/sbt/pull/2085
    #  https://github.com/sbt/sbt/pull/2160
    register('--incremental-caching', advanced=True, action='store_true', default=False,
             help='When set, the results of incremental compiles will be written to the cache. '
                  'This is unset by default, because it is generally a good precaution to cache '
                  'only clean/cold builds.')

    cls.register_jvm_tool(register,
                          'zinc',
                          classpath=[
                            JarDependency('org.pantsbuild', 'zinc', '1.0.12')
                          ],
                          main=cls._ZINC_MAIN,
                          custom_rules=[
                            # The compiler-interface and sbt-interface tool jars carry xsbt and
                            # xsbti interfaces that are used across the shaded tool jar boundary so
                            # we preserve these root packages wholesale along with the core scala
                            # APIs.
                            Shader.exclude_package('scala', recursive=True),
                            Shader.exclude_package('xsbt', recursive=True),
                            Shader.exclude_package('xsbti', recursive=True),
                          ])

    def sbt_jar(name, **kwargs):
      return JarDependency(org='com.typesafe.sbt', name=name, rev='0.13.9', **kwargs)

    cls.register_jvm_tool(register,
                          'compiler-interface',
                          classpath=[
                            sbt_jar(name='compiler-interface',
                                    classifier='sources',
                                    # We just want the single compiler-interface jar and not its
                                    # dep on scala-lang
                                    intransitive=True)
                          ])
    cls.register_jvm_tool(register,
                          'sbt-interface',
                          classpath=[
                            sbt_jar(name='sbt-interface',
                                    # We just want the single sbt-interface jar and not its dep
                                    # on scala-lang
                                    intransitive=True)
                          ])

    # By default we expect no plugin-jars classpath_spec is filled in by the user, so we accept an
    # empty classpath.
    cls.register_jvm_tool(register, 'plugin-jars', classpath=[])

  @classmethod
  def prepare(cls, options, round_manager):
    super(ZincCompile, cls).prepare(options, round_manager)
    ScalaPlatform.prepare_tools(round_manager)

  @property
  def incremental(self):
    """Zinc implements incremental compilation.

    Setting this property causes the task infrastructure to clone the previous
    results_dir for a target into the new results_dir for a target.
    """
    return self.get_options().incremental

  @property
  def cache_incremental(self):
    """Optionally write the results of incremental compiles to the cache."""
    return self.get_options().incremental_caching

  def select(self, target):
    return target.has_sources('.java') or target.has_sources('.scala')

  def select_source(self, source_file_path):
    return source_file_path.endswith('.java') or source_file_path.endswith('.scala')

  def __init__(self, *args, **kwargs):
    super(ZincCompile, self).__init__(*args, **kwargs)

    self._lazy_plugin_args = None

    # A directory to contain per-target subdirectories with apt processor info files.
    self._processor_info_dir = os.path.join(self.workdir, 'apt-processor-info')

    # Validate zinc options.
    ZincCompile.validate_arguments(self.context.log, self.get_options().whitelisted_args, self._args)

  def create_analysis_tools(self):
    return AnalysisTools(DistributionLocator.cached().real_home, ZincAnalysisParser(), ZincAnalysis,
                         get_buildroot(), self.get_options().pants_workdir)

  def zinc_classpath(self):
    # Zinc takes advantage of tools.jar if it's presented in classpath.
    # For example com.sun.tools.javac.Main is used for in process java compilation.
    def locate_tools_jar():
      try:
        return DistributionLocator.cached(jdk=True).find_libs(['tools.jar'])
      except DistributionLocator.Error:
        self.context.log.info('Failed to locate tools.jar. '
                              'Install a JDK to increase performance of Zinc.')
        return []

    return self.tool_classpath('zinc') + locate_tools_jar()

  def compiler_classpath(self):
    return ScalaPlatform.global_instance().compiler_classpath(self.context.products)

  def extra_compile_time_classpath_elements(self):
    # Classpath entries necessary for our compiler plugins.
    return self.plugin_jars()

  def plugin_jars(self):
    """The classpath entries for jars containing code for enabled plugins."""
    if self.get_options().scalac_plugins:
      return self.tool_classpath('plugin-jars')
    else:
      return []

  def plugin_args(self):
    if self._lazy_plugin_args is None:
      self._lazy_plugin_args = self._create_plugin_args()
    return self._lazy_plugin_args

  def _create_plugin_args(self):
    if not self.get_options().scalac_plugins:
      return []

    plugin_args = self.get_options().scalac_plugin_args
    active_plugins = self._find_plugins()
    ret = []
    for name, jar in active_plugins.items():
      ret.append('-S-Xplugin:{}'.format(jar))
      for arg in plugin_args.get(name, []):
        ret.append('-S-P:{}:{}'.format(name, arg))
    return ret

  def _find_plugins(self):
    """Returns a map from plugin name to plugin jar."""
    # Allow multiple flags and also comma-separated values in a single flag.
    plugin_names = set([p for val in self.get_options().scalac_plugins for p in val.split(',')])
    plugins = {}
    buildroot = get_buildroot()
    for jar in self.plugin_jars():
      with open_zip(jar, 'r') as jarfile:
        try:
          with closing(jarfile.open(_PLUGIN_INFO_FILE, 'r')) as plugin_info_file:
            plugin_info = ElementTree.parse(plugin_info_file).getroot()
          if plugin_info.tag != 'plugin':
            raise TaskError(
              'File {} in {} is not a valid scalac plugin descriptor'.format(_PLUGIN_INFO_FILE,
                                                                             jar))
          name = plugin_info.find('name').text
          if name in plugin_names:
            if name in plugins:
              raise TaskError('Plugin {} defined in {} and in {}'.format(name, plugins[name], jar))
            # It's important to use relative paths, as the compiler flags get embedded in the zinc
            # analysis file, and we port those between systems via the artifact cache.
            plugins[name] = os.path.relpath(jar, buildroot)
        except KeyError:
          pass

    unresolved_plugins = plugin_names - set(plugins.keys())
    if unresolved_plugins:
      raise TaskError('Could not find requested plugins: {}'.format(list(unresolved_plugins)))
    return plugins

  def write_extra_resources(self, compile_context):
    """Override write_extra_resources to produce plugin and annotation processor files."""
    target = compile_context.target
    if target.is_scalac_plugin and target.classname:
      self.write_plugin_info(compile_context.classes_dir, target)
    elif isinstance(target, AnnotationProcessor) and target.processors:
      processor_info_file = os.path.join(compile_context.classes_dir, _PROCESSOR_INFO_FILE)
      self._write_processor_info(processor_info_file, target.processors)

  def _write_processor_info(self, processor_info_file, processors):
    with safe_open(processor_info_file, 'w') as f:
      for processor in processors:
        f.write('{}\n'.format(processor.strip()))

  def compile(self, args, classpath, sources, classes_output_dir, upstream_analysis, analysis_file,
              log_file, settings, fatal_warnings):
    # We add compiler_classpath to ensure the scala-library jar is on the classpath.
    # TODO: This also adds the compiler jar to the classpath, which compiled code shouldn't
    # usually need. Be more selective?
    # TODO(John Sirois): Do we need to do this at all?  If adding scala-library to the classpath is
    # only intended to allow target authors to omit a scala-library dependency, then ScalaLibrary
    # already overrides traversable_dependency_specs to achieve the same end; arguably at a more
    # appropriate level and certainly at a more appropriate granularity.
    compile_classpath = self.compiler_classpath() + classpath

    self._verify_zinc_classpath(self.get_options().pants_workdir, compile_classpath)
    self._verify_zinc_classpath(self.get_options().pants_workdir, upstream_analysis.keys())

    zinc_args = []

    zinc_args.extend([
      '-log-level', self.get_options().level,
      '-analysis-cache', analysis_file,
      '-classpath', ':'.join(compile_classpath),
      '-d', classes_output_dir
    ])
    if not self.get_options().colors:
      zinc_args.append('-no-color')
    if not self.get_options().name_hashing:
      zinc_args.append('-no-name-hashing')
    if log_file:
      zinc_args.extend(['-capture-log', log_file])

    zinc_args.extend(['-compiler-interface', self.tool_jar('compiler-interface')])
    zinc_args.extend(['-sbt-interface', self.tool_jar('sbt-interface')])
    zinc_args.extend(['-scala-path', ':'.join(self.compiler_classpath())])

    zinc_args += self.plugin_args()
    if upstream_analysis:
      zinc_args.extend(['-analysis-map',
                        ','.join('{}:{}'.format(*kv) for kv in upstream_analysis.items())])

    zinc_args += args

    zinc_args.extend([
      '-C-source', '-C{}'.format(settings.source_level),
      '-C-target', '-C{}'.format(settings.target_level),
    ])
    zinc_args.extend(settings.args)

    if fatal_warnings:
      zinc_args.extend(['-S-Xfatal-warnings', '-C-Werror'])

    jvm_options = list(self._jvm_options)

    zinc_args.extend(sources)

    self.log_zinc_file(analysis_file)
    if self.runjava(classpath=self.zinc_classpath(),
                    main=self._ZINC_MAIN,
                    jvm_options=jvm_options,
                    args=zinc_args,
                    workunit_name='zinc',
                    workunit_labels=[WorkUnitLabel.COMPILER]):
      raise TaskError('Zinc compile failed.')

  @staticmethod
  def _verify_zinc_classpath(pants_workdir, classpath):
    for path in classpath:
      if not os.path.isabs(path):
        raise TaskError('Classpath entries provided to zinc should be absolute. ' + path + ' is not.')
      if os.path.relpath(path, pants_workdir).startswith(os.pardir):
        raise TaskError('Classpath entries provided to zinc should be in working directory. ' +
                        path + ' is not.')
      if path != os.path.normpath(path):
        raise TaskError('Classpath entries provided to zinc should be normalised (i.e. without ".." and "."). ' +
                        path + ' is not.')

  def log_zinc_file(self, analysis_file):
    self.context.log.debug('Calling zinc on: {} ({})'
                           .format(analysis_file,
                                   hash_file(analysis_file).upper()
                                   if os.path.exists(analysis_file)
                                   else 'nonexistent'))
