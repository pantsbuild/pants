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
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_utils import ZincUtils
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.option.options import Options
from pants.util.contextutil import open_zip
from pants.util.dirutil import safe_open


# Well known metadata file required to register scalac plugins with nsc.
_PLUGIN_INFO_FILE = 'scalac-plugin.xml'


class ZincCompile(JvmCompile):
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
    register('--plugins', action='append', help='Use these scalac plugins.')
    register('--plugin-args', advanced=True, type=Options.dict, default={},
             help='Map from plugin name to list of arguments for that plugin.')
    register('--name-hashing', action='store_true', default=False, help='Use zinc name hashing.')
    cls.register_jvm_tool(register, 'zinc')
    cls.register_jvm_tool(register, 'plugin-jars')

  def __init__(self, *args, **kwargs):
    super(ZincCompile, self).__init__(*args, **kwargs)

    # Set up the zinc utils.
    color = self.get_options().colors
    self._zinc_utils = ZincUtils(context=self.context,
                                 nailgun_task=self,
                                 jvm_options=self._jvm_options,
                                 color=color,
                                 log_level=self.get_options().level)

    # A directory independent of any other classpath which can contain per-target
    # plugin resource files.
    self._plugin_info_dir = os.path.join(self.workdir, 'scalac-plugin-info')
    self._lazy_plugin_args = None

  def create_analysis_tools(self):
    return AnalysisTools(self.context.java_home, ZincAnalysisParser(), ZincAnalysis)

  def zinc_classpath(self):
    return self.tool_classpath('zinc')

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

  def name_hashing(self):
    return self.get_options().name_hashing

  def _create_plugin_args(self):
    if not self.get_options().plugins:
      return []

    plugin_args = self.get_options().plugin_args
    active_plugins = self.find_plugins()
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

  # Invalidate caches if the toolchain changes.
  def _language_platform_version_info(self):
    ret = []

    # Go through all the bootstrap tools required to compile.
    targets = (ScalaPlatform.global_instance().tool_targets(self.context, 'scalac') +
               self.tool_targets(self.context, 'zinc'))
    for lib in (t for t in targets if isinstance(t, JarLibrary)):
      for jar in lib.jar_dependencies:
        ret.append(jar.cache_key())

    # We must invalidate on the set of plugins and their settings.
    ret.extend(self.plugin_args())

    # Invalidate if any compiler args change.
    # Note that while some args are obviously important for invalidation (e.g., the jvm target
    # version), some might not be. However we must invalidated on all the args, because Zinc
    # ignores analysis files if the compiler args they were created with are different from the
    # current ones, and does a full recompile. So if we allow cached artifacts with those analysis
    # files to be used, Zinc will do unnecessary full recompiles on subsequent edits.
    ret.extend(self._args)

    # Invalidate if use of name hashing changes.
    ret.append('name-hashing-{0}'.format('on' if self.get_options().name_hashing else 'off'))

    return ret

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

  def compile(self, args, classpath, sources, classes_output_dir, upstream_analysis, analysis_file):
    return self._zinc_utils.compile(args, classpath, sources,
                                    classes_output_dir, analysis_file, upstream_analysis)


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
