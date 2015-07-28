# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import textwrap
from contextlib import closing
from xml.etree import ElementTree

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.jvm_compile.analysis_tools import AnalysisTools
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis import ZincAnalysis
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis_parser import ZincAnalysisParser
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.hash_utils import hash_file
from pants.base.workunit import WorkUnit
from pants.java.distribution.distribution import Distribution
from pants.java.jar.shader import Shader
from pants.option.options import Options
from pants.util.contextutil import open_zip
from pants.util.dirutil import relativize_paths, safe_open


# Well known metadata file required to register scalac plugins with nsc.
_PLUGIN_INFO_FILE = 'scalac-plugin.xml'


class ZincCompile(JvmCompile):
  _ZINC_MAIN = 'org.pantsbuild.zinc.Main'

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

  @classmethod
  def global_subsystems(cls):
    return super(ZincCompile, cls).global_subsystems() + (ScalaPlatform, )

  @classmethod
  def get_args_default(cls, bootstrap_option_values):
    return ('-S-encoding', '-SUTF-8','-S-g:vars')

  @classmethod
  def get_warning_args_default(cls):
    return ('-S-deprecation', '-S-unchecked')

  @classmethod
  def get_no_warning_args_default(cls):
    return ('-S-nowarn',)

  @classmethod
  def register_options(cls, register):
    super(ZincCompile, cls).register_options(register)
    register('--plugins', action='append', fingerprint=True,
             help='Use these scalac plugins.')
    register('--plugin-args', advanced=True, type=Options.dict, default={}, fingerprint=True,
             help='Map from plugin name to list of arguments for that plugin.')
    register('--name-hashing', action='store_true', default=False, fingerprint=True,
             help='Use zinc name hashing.')

    cls.register_jvm_tool(register,
                          'zinc',
                          main=cls._ZINC_MAIN,
                          custom_rules=[
                            # The compiler-interface and sbt-interface tool jars carry xsbt and
                            # xsbti interfaces that are used across the shaded tool jar boundary so
                            # we preserve these root packages wholesale along with the core scala
                            # APIs.
                            Shader.exclude_package('scala', recursive=True),
                            Shader.exclude_package('xsbt', recursive=True),
                            Shader.exclude_package('xsbti', recursive=True),
                          ],
                          fingerprint=True)
    cls.register_jvm_tool(register, 'compiler-interface', fingerprint=True)
    cls.register_jvm_tool(register, 'sbt-interface', fingerprint=True)

    cls.register_jvm_tool(register, 'plugin-jars', default=[], fingerprint=True)

  def __init__(self, *args, **kwargs):
    super(ZincCompile, self).__init__(*args, **kwargs)

    # A directory independent of any other classpath which can contain per-target
    # plugin resource files.
    self._plugin_info_dir = os.path.join(self.workdir, 'scalac-plugin-info')
    self._lazy_plugin_args = None

  def create_analysis_tools(self):
    return AnalysisTools(self.context.java_home, ZincAnalysisParser(), ZincAnalysis)

  def zinc_classpath(self):
    # Zinc takes advantage of tools.jar if it's presented in classpath.
    # For example com.sun.tools.javac.Main is used for in process java compilation.
    def locate_tools_jar():
      try:
        return Distribution.cached(jdk=True).find_libs(['tools.jar'])
      except Distribution.Error:
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
    if self.get_options().plugins:
      return self.tool_classpath('plugin-jars')
    else:
      return []

  def plugin_args(self):
    if self._lazy_plugin_args is None:
      self._lazy_plugin_args = self._create_plugin_args()
    return self._lazy_plugin_args

  def _create_plugin_args(self):
    if not self.get_options().plugins:
      return []

    plugin_args = self.get_options().plugin_args
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
    plugin_names = set([p for val in self.get_options().plugins for p in val.split(',')])
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

  def extra_products(self, target):
    """Override extra_products to produce a plugin information file."""
    ret = []
    if target.is_scalac_plugin and target.classname:
      # NB: We don't yet support explicit in-line compilation of scala compiler plugins from
      # the workspace to be used in subsequent compile rounds like we do for annotation processors
      # with javac. This would require another GroupTask similar to AptCompile, but for scala.
      root, plugin_info_file = self.write_plugin_info(self._plugin_info_dir, target)
      ret.append((root, [plugin_info_file]))
    return ret

  def compile(self, args, classpath, sources, classes_output_dir, upstream_analysis, analysis_file, log_file):
    # We add compiler_classpath to ensure the scala-library jar is on the classpath.
    # TODO: This also adds the compiler jar to the classpath, which compiled code shouldn't
    # usually need. Be more selective?
    # TODO(John Sirois): Do we need to do this at all?  If adding scala-library to the classpath is
    # only intended to allow target authors to omit a scala-library dependency, then ScalaLibrary
    # already overrides traversable_dependency_specs to achieve the same end; arguably at a more
    # appropriate level and certainly at a more appropriate granularity.
    relativized_classpath = relativize_paths(self.compiler_classpath() + classpath, get_buildroot())

    zinc_args = []

    zinc_args.extend([
      '-log-level', self.get_options().level,
      '-analysis-cache', analysis_file,
      '-classpath', ':'.join(relativized_classpath),
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

    zinc_args.extend(sources)

    self.log_zinc_file(analysis_file)
    if self.runjava(classpath=self.zinc_classpath(),
                    main=self._ZINC_MAIN,
                    jvm_options=self._jvm_options,
                    args=zinc_args,
                    workunit_name='zinc',
                    workunit_labels=[WorkUnit.COMPILER]):
      raise TaskError('Zinc compile failed.')

  def log_zinc_file(self, analysis_file):
    self.context.log.debug('Calling zinc on: {} ({})'
                           .format(analysis_file,
                                   hash_file(analysis_file).upper()
                                   if os.path.exists(analysis_file)
                                   else 'nonexistent'))

class ScalaZincCompile(ZincCompile):
  _language = 'scala'
  _file_suffix = '.scala'


class JavaZincCompile(ZincCompile):
  _language = 'java'
  _file_suffix = '.java'

  @classmethod
  def get_args_default(cls, bootstrap_option_values):
    return super(JavaZincCompile, cls).get_args_default(bootstrap_option_values) + ('-java-only',)

  @classmethod
  def name(cls):
    # Use a different name from 'java' so options from JMake version won't interfere.
    return "zinc-java"

  @classmethod
  def register_options(cls, register):
    super(JavaZincCompile, cls).register_options(register)
    register('--enabled', action='store_true', default=False,
             help='Use zinc to compile Java targets')

  def select(self, target):
    return self.get_options().enabled and super(JavaZincCompile, self).select(target)
