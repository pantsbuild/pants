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
from pants.backend.jvm.tasks.jvm_compile.analysis_tools import AnalysisTools
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis import ZincAnalysis
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis_parser import ZincAnalysisParser
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.hash_utils import hash_file
from pants.base.workunit import WorkUnitLabel
from pants.java.distribution.distribution import DistributionLocator
from pants.java.jar.shader import Shader
from pants.option.custom_types import dict_option
from pants.util.contextutil import open_zip
from pants.util.dirutil import relativize_paths, safe_open


# Well known metadata file required to register scalac plugins with nsc.
_PLUGIN_INFO_FILE = 'scalac-plugin.xml'


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

  @classmethod
  def subsystem_dependencies(cls):
    return super(ZincCompile, cls).subsystem_dependencies() + (ScalaPlatform, DistributionLocator)

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
    register('--plugins', advanced=True, action='append', fingerprint=True,
             help='Use these scalac plugins.')
    register('--plugin-args', advanced=True, type=dict_option, default={}, fingerprint=True,
             help='Map from plugin name to list of arguments for that plugin.')
    register('--name-hashing', advanced=True, action='store_true', default=False, fingerprint=True,
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
                          ])
    cls.register_jvm_tool(register, 'compiler-interface')
    cls.register_jvm_tool(register, 'sbt-interface')

    cls.register_jvm_tool(register, 'plugin-jars', default=[])

  def select(self, target):
    return target.has_sources('.java') or target.has_sources('.scala')

  def select_source(self, source_file_path):
    return source_file_path.endswith('.java') or source_file_path.endswith('.scala')

  def __init__(self, *args, **kwargs):
    super(ZincCompile, self).__init__(*args, **kwargs)

    # A directory independent of any other classpath which can contain per-target
    # plugin resource files.
    self._plugin_info_dir = os.path.join(self.workdir, 'scalac-plugin-info')
    self._lazy_plugin_args = None

  def create_analysis_tools(self):
    return AnalysisTools(DistributionLocator.cached().real_home, ZincAnalysisParser(), ZincAnalysis)

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
    return []

  def plugin_jars(self):
    return []

  def plugin_args(self):
    return []

  def extra_products(self, target):
    return []

  def compile(self, args, classpath, sources, classes_output_dir, upstream_analysis, analysis_file,
              log_file, settings):
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

    zinc_args.extend([
      '-C-source', '-C{}'.format(settings.source_level),
      '-C-target', '-C{}'.format(settings.target_level),
    ])
    zinc_args.extend(settings.args)

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

  def log_zinc_file(self, analysis_file):
    self.context.log.debug('Calling zinc on: {} ({})'
                           .format(analysis_file,
                                   hash_file(analysis_file).upper()
                                   if os.path.exists(analysis_file)
                                   else 'nonexistent'))
