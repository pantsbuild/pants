# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import re
import textwrap
from contextlib import closing
from xml.etree import ElementTree

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.javac_plugin import JavacPlugin
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scalac_plugin import ScalacPlugin
from pants.backend.jvm.tasks.jvm_compile.analysis_tools import AnalysisTools
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_analysis import ZincAnalysis
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_analysis_parser import ZincAnalysisParser
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.hash_utils import hash_file
from pants.base.workunit import WorkUnitLabel
from pants.java.distribution.distribution import Distribution, DistributionLocator
from pants.util.contextutil import open_zip
from pants.util.dirutil import safe_open
from pants.util.memo import memoized_method, memoized_property


# Well known metadata file required to register scalac plugins with nsc.
_SCALAC_PLUGIN_INFO_FILE = 'scalac-plugin.xml'

# Well known metadata file to register javac plugins.
_JAVAC_PLUGIN_INFO_FILE = 'META-INF/services/com.sun.source.util.Plugin'

# Well known metadata file to register annotation processors with a java 1.6+ compiler.
_PROCESSOR_INFO_FILE = 'META-INF/services/javax.annotation.processing.Processor'


logger = logging.getLogger(__name__)


class BaseZincCompile(JvmCompile):
  """An abstract base class for zinc compilation tasks."""

  _ZINC_MAIN = 'org.pantsbuild.zinc.Main'

  _supports_concurrent_execution = True

  @staticmethod
  def _write_scalac_plugin_info(resources_dir, scalac_plugin_target):
    scalac_plugin_info_file = os.path.join(resources_dir, _SCALAC_PLUGIN_INFO_FILE)
    with safe_open(scalac_plugin_info_file, 'w') as f:
      f.write(textwrap.dedent("""
        <plugin>
          <name>{}</name>
          <classname>{}</classname>
        </plugin>
      """.format(scalac_plugin_target.plugin, scalac_plugin_target.classname)).strip())

  @staticmethod
  def _write_javac_plugin_info(resources_dir, javac_plugin_target):
    javac_plugin_info_file = os.path.join(resources_dir, _JAVAC_PLUGIN_INFO_FILE)
    with safe_open(javac_plugin_info_file, 'w') as f:
      f.write(javac_plugin_target.classname)

  @staticmethod
  def validate_arguments(log, whitelisted_args, args):
    """Validate that all arguments match whitelisted regexes."""
    valid_patterns = {re.compile(p): v for p, v in whitelisted_args.items()}

    def validate(idx):
      arg = args[idx]
      for pattern, has_argument in valid_patterns.items():
        if pattern.match(arg):
          return 2 if has_argument else 1
      log.warn("Zinc argument '{}' is not supported, and is subject to change/removal!".format(arg))
      return 1

    arg_index = 0
    while arg_index < len(args):
      arg_index += validate(arg_index)

  @staticmethod
  def _get_zinc_arguments(settings):
    """Extracts and formats the zinc arguments given in the jvm platform settings.

    This is responsible for the symbol substitution which replaces $JAVA_HOME with the path to an
    appropriate jvm distribution.

    :param settings: The jvm platform settings from which to extract the arguments.
    :type settings: :class:`JvmPlatformSettings`
    """
    zinc_args = [
      '-C-source', '-C{}'.format(settings.source_level),
      '-C-target', '-C{}'.format(settings.target_level),
    ]
    if settings.args:
      settings_args = settings.args
      if any('$JAVA_HOME' in a for a in settings.args):
        try:
          distribution = JvmPlatform.preferred_jvm_distribution([settings], strict=True)
        except DistributionLocator.Error:
          distribution = JvmPlatform.preferred_jvm_distribution([settings], strict=False)
        logger.debug('Substituting "$JAVA_HOME" with "{}" in jvm-platform args.'
                     .format(distribution.home))
        settings_args = (a.replace('$JAVA_HOME', distribution.home) for a in settings.args)
      zinc_args.extend(settings_args)
    return zinc_args

  @classmethod
  def compiler_plugin_types(cls):
    """A tuple of target types which are compiler plugins."""
    return (AnnotationProcessor, JavacPlugin, ScalacPlugin)

  @classmethod
  def get_jvm_options_default(cls, bootstrap_option_values):
    return ('-Dfile.encoding=UTF-8', '-Dzinc.analysis.cache.limit=1000',
            '-Djava.awt.headless=true', '-Xmx2g')

  @classmethod
  def get_args_default(cls, bootstrap_option_values):
    return ('-C-encoding', '-CUTF-8', '-S-encoding', '-SUTF-8', '-S-g:vars')

  @classmethod
  def get_warning_args_default(cls):
    return ('-C-deprecation', '-C-Xlint:all', '-C-Xlint:-serial', '-C-Xlint:-path',
            '-S-deprecation', '-S-unchecked', '-S-Xlint')

  @classmethod
  def get_no_warning_args_default(cls):
    return ('-C-nowarn', '-C-Xlint:none', '-S-nowarn', '-S-Xlint:none', )

  @classmethod
  def get_fatal_warnings_enabled_args_default(cls):
    return ('-S-Xfatal-warnings', '-C-Werror')

  @classmethod
  def get_fatal_warnings_disabled_args_default(cls):
    return ()

  @classmethod
  def register_options(cls, register):
    super(BaseZincCompile, cls).register_options(register)
    # TODO: disable by default because it breaks dependency parsing:
    #   https://github.com/pantsbuild/pants/issues/2224
    # ...also, as of sbt 0.13.9, it is significantly slower for cold builds.
    register('--name-hashing', advanced=True, type=bool, fingerprint=True,
             help='Use zinc name hashing.')
    register('--whitelisted-args', advanced=True, type=dict,
             default={
               '-S.*': False,
               '-C.*': False,
               '-file-filter': True,
               '-msg-filter': True,
               },
             help='A dict of option regexes that make up pants\' supported API for zinc. '
                  'Options not listed here are subject to change/removal. The value of the dict '
                  'indicates that an option accepts an argument.')

    register('--incremental', advanced=True, type=bool, default=True,
             help='When set, zinc will use sub-target incremental compilation, which dramatically '
                  'improves compile performance while changing large targets. When unset, '
                  'changed targets will be compiled with an empty output directory, as if after '
                  'running clean-all.')

    # TODO: Defaulting to false due to a few upstream issues for which we haven't pulled down fixes:
    #  https://github.com/sbt/sbt/pull/2085
    #  https://github.com/sbt/sbt/pull/2160
    register('--incremental-caching', advanced=True, type=bool,
             help='When set, the results of incremental compiles will be written to the cache. '
                  'This is unset by default, because it is generally a good precaution to cache '
                  'only clean/cold builds.')

    cls.register_jvm_tool(register,
                          'zinc',
                          classpath=[
                            # NB: This is explicitly a `_2.10` JarDependency rather than a
                            # ScalaJarDependency. The latter would pick up the platform in a users'
                            # repo, whereas this binary is shaded and independent of the target
                            # platform version.
                            JarDependency('org.pantsbuild', 'zinc_2.10', '0.0.3')
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

  @classmethod
  def prepare(cls, options, round_manager):
    super(BaseZincCompile, cls).prepare(options, round_manager)
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

  def __init__(self, *args, **kwargs):
    super(BaseZincCompile, self).__init__(*args, **kwargs)
    self.set_distribution(jdk=True)
    try:
      # Zinc uses com.sun.tools.javac.Main for in-process java compilation.
      # If not present Zinc attempts to spawn an external javac, but we want to keep
      # everything in our selected distribution, so we don't allow it to do that.
      self._tools_jar = self.dist.find_libs(['tools.jar'])
    except Distribution.Error as e:
      raise TaskError(e)

    # A directory to contain per-target subdirectories with apt processor info files.
    self._processor_info_dir = os.path.join(self.workdir, 'apt-processor-info')

    # Validate zinc options.
    ZincCompile.validate_arguments(self.context.log, self.get_options().whitelisted_args,
                                   self._args)

  def select(self, target):
    raise NotImplementedError()

  def select_source(self, source_file_path):
    raise NotImplementedError()

  def create_analysis_tools(self):
    return AnalysisTools(self.dist.real_home, ZincAnalysisParser(), ZincAnalysis,
                         get_buildroot(), self.get_options().pants_workdir)

  def zinc_classpath(self):
    return self.tool_classpath('zinc') + self._tools_jar

  def compiler_classpath(self):
    return ScalaPlatform.global_instance().compiler_classpath(self.context.products)

  def extra_compile_time_classpath_elements(self):
    # Classpath entries necessary for our compiler plugins.
    return self.scalac_plugin_jars

  def javac_plugin_args(self, exclude):
    """param tuple exclude: names of plugins to exclude, even if requested."""
    raise NotImplementedError()

  @property
  def scalac_plugin_jars(self):
    """The classpath entries for jars containing code for enabled scalac plugins."""
    raise NotImplementedError()

  @property
  def scalac_plugin_args(self):
    raise NotImplementedError()

  def write_extra_resources(self, compile_context):
    """Override write_extra_resources to produce plugin and annotation processor files."""
    target = compile_context.target
    if isinstance(target, ScalacPlugin):
      self._write_scalac_plugin_info(compile_context.classes_dir, target)
    elif isinstance(target, JavacPlugin):
      self._write_javac_plugin_info(compile_context.classes_dir, target)
    elif isinstance(target, AnnotationProcessor) and target.processors:
      processor_info_file = os.path.join(compile_context.classes_dir, _PROCESSOR_INFO_FILE)
      self._write_processor_info(processor_info_file, target.processors)

  def _write_processor_info(self, processor_info_file, processors):
    with safe_open(processor_info_file, 'w') as f:
      for processor in processors:
        f.write('{}\n'.format(processor.strip()))

  def compile(self, args, classpath, sources, classes_output_dir, upstream_analysis, analysis_file,
              log_file, settings, fatal_warnings, javac_plugins_to_exclude):
    self._verify_zinc_classpath(classpath)
    self._verify_zinc_classpath(upstream_analysis.keys())

    zinc_args = []

    zinc_args.extend([
      '-log-level', self.get_options().level,
      '-analysis-cache', analysis_file,
      '-classpath', ':'.join(classpath),
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

    zinc_args.extend(self.javac_plugin_args(javac_plugins_to_exclude))
    zinc_args.extend(self.scalac_plugin_args)
    if upstream_analysis:
      zinc_args.extend(['-analysis-map',
                        ','.join('{}:{}'.format(*kv) for kv in upstream_analysis.items())])

    zinc_args.extend(args)
    zinc_args.extend(self._get_zinc_arguments(settings))

    if fatal_warnings:
      zinc_args.extend(self.get_options().fatal_warnings_enabled_args)
    else:
      zinc_args.extend(self.get_options().fatal_warnings_disabled_args)

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

  def _verify_zinc_classpath(self, classpath):
    def is_outside(path, putative_parent):
      return os.path.relpath(path, putative_parent).startswith(os.pardir)

    for path in classpath:
      if not os.path.isabs(path):
        raise TaskError('Classpath entries provided to zinc should be absolute. '
                        '{} is not.'.format(path))
      if is_outside(path, self.get_options().pants_workdir) and is_outside(path, self.dist.home):
        raise TaskError('Classpath entries provided to zinc should be in working directory or '
                        'part of the JDK. {} is not.'.format(path))
      if path != os.path.normpath(path):
        raise TaskError('Classpath entries provided to zinc should be normalized '
                        '(i.e. without ".." and "."). {} is not.'.format(path))

  def log_zinc_file(self, analysis_file):
    self.context.log.debug('Calling zinc on: {} ({})'
                           .format(analysis_file,
                                   hash_file(analysis_file).upper()
                                   if os.path.exists(analysis_file)
                                   else 'nonexistent'))


class ZincCompile(BaseZincCompile):
  """Compile Scala and Java code using Zinc."""

  _name = 'zinc'

  @classmethod
  def register_options(cls, register):
    super(ZincCompile, cls).register_options(register)
    register('--javac-plugins', advanced=True, type=list, fingerprint=True,
             help='Use these javac plugins.')
    register('--javac-plugin-args', advanced=True, type=dict, default={}, fingerprint=True,
             help='Map from javac plugin name to list of arguments for that plugin.')

    register('--scalac-plugins', advanced=True, type=list, fingerprint=True,
             help='Use these scalac plugins.')
    register('--scalac-plugin-args', advanced=True, type=dict, default={}, fingerprint=True,
             help='Map from scalac plugin name to list of arguments for that plugin.')

    # Scalac plugin jars must already be available at compile time, because they need to be listed
    # on the scalac command line. We search for available plugins on the tool classpath provided
    # by //:scalac-plugin-jars.  Therefore any in-repo plugins must be published, so they can be
    # pulled in as a tool.
    # TODO: Ability to use built in-repo plugins via their context jars.
    cls.register_jvm_tool(register, 'scalac-plugin-jars', classpath=[])

  @classmethod
  def product_types(cls):
    return ['runtime_classpath', 'classes_by_source', 'product_deps_by_src']

  def select(self, target):
    # Require that targets are marked for JVM compilation, to differentiate from
    # targets owned by the scalajs contrib module.
    if not isinstance(target, JvmTarget):
      return False
    return target.has_sources('.java') or target.has_sources('.scala')

  def select_source(self, source_file_path):
    return source_file_path.endswith('.java') or source_file_path.endswith('.scala')

  @memoized_method
  def javac_plugin_args(self, exclude):
    if not self.get_options().javac_plugins:
      return []

    exclude = exclude or []

    # Allow multiple flags and also comma-separated values in a single flag.
    active_plugins = set([p for val in self.get_options().javac_plugins
                          for p in val.split(',')]).difference(exclude)
    ret = []
    javac_plugin_args = self.get_options().javac_plugin_args
    for name in active_plugins:
      # Note: Args are separated by spaces, and there is no way to escape embedded spaces, as
      # javac's Main does a simple split on these strings.
      plugin_args = javac_plugin_args.get(name, [])
      for arg in plugin_args:
        if ' ' in arg:
          raise TaskError('javac plugin args must not contain spaces '
                          '(arg {} for plugin {})'.format(arg, name))
      ret.append('-C-Xplugin:{} {}'.format(name, ' '.join(plugin_args)))
    return ret

  @memoized_property
  def scalac_plugin_jars(self):
    """The classpath entries for jars containing code for enabled scalac plugins."""
    if self.get_options().scalac_plugins:
      return self.tool_classpath('scalac-plugin-jars')
    else:
      return []

  @memoized_property
  def scalac_plugin_args(self):
    if not self.get_options().scalac_plugins:
      return []

    scalac_plugin_args = self.get_options().scalac_plugin_args
    active_plugins = self._find_scalac_plugins()
    ret = []
    for name, jar in active_plugins.items():
      ret.append('-S-Xplugin:{}'.format(jar))
      for arg in scalac_plugin_args.get(name, []):
        ret.append('-S-P:{}:{}'.format(name, arg))
    return ret

  def _find_scalac_plugins(self):
    """Returns a map from plugin name to plugin jar."""
    # Allow multiple flags and also comma-separated values in a single flag.
    plugin_names = set([p for val in self.get_options().scalac_plugins for p in val.split(',')])
    plugins = {}
    buildroot = get_buildroot()
    for jar in self.scalac_plugin_jars:
      with open_zip(jar, 'r') as jarfile:
        try:
          with closing(jarfile.open(_SCALAC_PLUGIN_INFO_FILE, 'r')) as plugin_info_file:
            plugin_info = ElementTree.parse(plugin_info_file).getroot()
          if plugin_info.tag != 'plugin':
            raise TaskError(
              'File {} in {} is not a valid scalac plugin descriptor'.format(
                  _SCALAC_PLUGIN_INFO_FILE, jar))
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
