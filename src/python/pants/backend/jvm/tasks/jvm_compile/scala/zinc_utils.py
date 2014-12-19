# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import closing
from itertools import chain
import os
import textwrap
from xml.etree import ElementTree

from twitter.common.collections import OrderedDict

from pants.backend.jvm.jvm_tool_bootstrapper import JvmToolBootstrapper
from pants.backend.jvm.scala.target_platform import TargetPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.hash_utils import hash_file
from pants.base.workunit import WorkUnit
from pants.util.contextutil import open_zip as open_jar
from pants.util.dirutil import relativize_paths, safe_open


# Well known metadata file required to register scalac plugins with nsc.
_PLUGIN_INFO_FILE = 'scalac-plugin.xml'


class ZincUtils(object):
  """Convenient wrapper around zinc invocations.

  Instances are immutable, and all methods are reentrant (assuming that the java_runner is).
  """

  class DepLookupError(AddressLookupError):
    """Thrown when a dependency can't be found."""
    pass

  _ZINC_MAIN = 'com.typesafe.zinc.Main'

  def __init__(self, context, nailgun_task, jvm_options, color=True, log_level='info'):
    self.context = context
    self._nailgun_task = nailgun_task  # We run zinc on this task's behalf.
    self._jvm_options = jvm_options
    self._color = color
    self._log_level = log_level
    self._jvm_tool_bootstrapper = JvmToolBootstrapper(self.context.products)

    # The target scala version.
    self._compile_bootstrap_key = 'scalac'
    self._compile_bootstrap_tools = TargetPlatform(config=context.config).compiler_specs
    self._jvm_tool_bootstrapper.register_jvm_tool(self._compile_bootstrap_key,
                                                  self._compile_bootstrap_tools,
                                                  ini_section='scala-compile',
                                                  ini_key='compile-bootstrap-tools')

    # The zinc version (and the scala version it needs, which may differ from the target version).
    self._zinc_bootstrap_key = 'zinc'
    self._jvm_tool_bootstrapper.register_jvm_tool_from_config(self._zinc_bootstrap_key,
                                                              context.config,
                                                              ini_section='scala-compile',
                                                              ini_key='zinc-bootstrap-tools',
                                                              default=['//:zinc'])

    # Compiler plugins.
    plugins_bootstrap_tools = context.config.getlist('scala-compile',
                                                     'scalac-plugin-bootstrap-tools',
                                                     default=[])
    if plugins_bootstrap_tools:
      self._plugins_bootstrap_key = 'plugins'
      self._jvm_tool_bootstrapper.register_jvm_tool(self._plugins_bootstrap_key,
                                                    plugins_bootstrap_tools,
                                                    ini_section='scala-compile',
                                                    ini_key='scalac-plugin-bootstrap-tools')
    else:
      self._plugins_bootstrap_key = None

  @property
  def _zinc_classpath(self):
    return self._jvm_tool_bootstrapper.get_jvm_tool_classpath(self._zinc_bootstrap_key)

  @property
  def _compiler_classpath(self):
    return self._jvm_tool_bootstrapper.get_jvm_tool_classpath(self._compile_bootstrap_key)

  @property
  def _plugin_jars(self):
    if self._plugins_bootstrap_key:
      return self._jvm_tool_bootstrapper.get_jvm_tool_classpath(self._plugins_bootstrap_key)
    else:
      return []

  @property
  def _zinc_jar_args(self):
    zinc_jars = ZincUtils.identify_zinc_jars(self._zinc_classpath)
    # The zinc jar names are also the flag names.
    return (list(chain.from_iterable([['-%s' % name, jarpath]
                                     for (name, jarpath) in zinc_jars.items()])) +
            ['-scala-path', ':'.join(self._compiler_classpath)])

  def _plugin_args(self):
    # Allow multiple flags and also comma-separated values in a single flag.
    plugin_names = [p for val in self._nailgun_task.get_options().plugins for p in val.split(',')]
    plugin_args = self.context.config.getdict('compile.scala', 'plugin-args', default={})
    active_plugins = self.find_plugins(plugin_names)

    ret = []
    for name, jar in active_plugins.items():
      ret.append('-S-Xplugin:%s' % jar)
      for arg in plugin_args.get(name, []):
        ret.append('-S-P:%s:%s' % (name, arg))
    return ret

  def plugin_jars(self):
    """The jars containing code for enabled plugins."""
    return self._plugin_jars

  def _run_zinc(self, args, workunit_name='zinc', workunit_labels=None):
    zinc_args = [
      '-log-level', self._log_level,
    ]
    if not self._color:
      zinc_args.append('-no-color')
    zinc_args.extend(self._zinc_jar_args)
    zinc_args.extend(args)
    return self._nailgun_task.runjava(classpath=self._zinc_classpath,
                                      main=ZincUtils._ZINC_MAIN,
                                      jvm_options=self._jvm_options,
                                      args=zinc_args,
                                      workunit_name=workunit_name,
                                      workunit_labels=workunit_labels)

  def platform_version_info(self):
    ret = []

    # Go through all the bootstrap tools required to compile.
    for target in self._compile_bootstrap_tools:
      # Resolve to their actual targets.
      try:
        deps = self.context.resolve(target)
      except AddressLookupError as e:
        raise self.DepLookupError("{message}\n  referenced from [{section}] key: {key} in pants.ini"
                                  .format(message=e, section='scala-compile',
                                          key='compile-bootstrap-tools'))

      for lib in (t for t in deps if isinstance(t, JarLibrary)):
        for jar in lib.jar_dependencies:
          ret.append(jar.cache_key())
    return sorted(ret)

  @staticmethod
  def _get_compile_args(opts, classpath, sources, output_dir, analysis_file, upstream_analysis_files):
    args = list(opts)  # Make a copy

    if upstream_analysis_files:
      args.extend(
        ['-analysis-map', ','.join(['%s:%s' % kv for kv in upstream_analysis_files.items()])])

    relative_classpath = relativize_paths(classpath, get_buildroot())
    args.extend([
      '-analysis-cache', analysis_file,
      '-classpath', ':'.join(relative_classpath),
      '-d', output_dir
    ])
    args.extend(sources)
    return args

  def compile(self, opts, classpath, sources, output_dir, analysis_file, upstream_analysis_files):

    # We add compiler_classpath to ensure the scala-library jar is on the classpath.
    # TODO: This also adds the compiler jar to the classpath, which compiled code shouldn't
    # usually need. Be more selective?
    big_classpath = self._compiler_classpath + classpath
    args = ZincUtils._get_compile_args(opts + self._plugin_args(), big_classpath,
                                       sources, output_dir, analysis_file, upstream_analysis_files)
    self.log_zinc_file(analysis_file)
    if self._run_zinc(args, workunit_labels=[WorkUnit.COMPILER]):
      raise TaskError('Zinc compile failed.')

  @staticmethod
  def write_plugin_info(resources_dir, target):
    root = os.path.join(resources_dir, target.id)
    plugin_info_file = os.path.join(root, _PLUGIN_INFO_FILE)
    with safe_open(plugin_info_file, 'w') as f:
      f.write(textwrap.dedent('''
        <plugin>
          <name>%s</name>
          <classname>%s</classname>
        </plugin>
      ''' % (target.plugin, target.classname)).strip())
    return root, plugin_info_file

  # These are the names of the various jars zinc needs. They are, conveniently and
  # non-coincidentally, the names of the flags used to pass the jar locations to zinc.
  ZINC_JAR_NAMES = ['compiler-interface', 'sbt-interface']

  @staticmethod
  def identify_zinc_jars(zinc_classpath):
    """Find the named jars in the zinc classpath.

    TODO: Make these mappings explicit instead of deriving them by jar name heuristics.
    """
    ret = OrderedDict()
    ret.update(ZincUtils.identify_jars(ZincUtils.ZINC_JAR_NAMES, zinc_classpath))
    return ret

  @staticmethod
  def identify_jars(names, jars):
    jars_by_name = {}
    jars_and_filenames = [(x, os.path.basename(x)) for x in jars]

    for name in names:
      jar_for_name = None
      for jar, filename in jars_and_filenames:
        if filename.startswith(name):
          jar_for_name = jar
          break
      if jar_for_name is None:
        raise TaskError('Couldn\'t find jar named %s' % name)
      else:
        jars_by_name[name] = jar_for_name
    return jars_by_name

  def find_plugins(self, plugin_names):
    """Returns a map from plugin name to plugin jar."""
    plugin_names = set(plugin_names)
    plugins = {}
    buildroot = get_buildroot()
    # plugin_jars is the universe of all possible plugins and their transitive deps.
    # Here we select the ones to actually use.
    for jar in self.plugin_jars():
      with open_jar(jar, 'r') as jarfile:
        try:
          with closing(jarfile.open(_PLUGIN_INFO_FILE, 'r')) as plugin_info_file:
            plugin_info = ElementTree.parse(plugin_info_file).getroot()
          if plugin_info.tag != 'plugin':
            raise TaskError(
              'File %s in %s is not a valid scalac plugin descriptor' % (_PLUGIN_INFO_FILE, jar))
          name = plugin_info.find('name').text
          if name in plugin_names:
            if name in plugins:
              raise TaskError('Plugin %s defined in %s and in %s' % (name, plugins[name], jar))
            # It's important to use relative paths, as the compiler flags get embedded in the zinc
            # analysis file, and we port those between systems via the artifact cache.
            plugins[name] = os.path.relpath(jar, buildroot)
        except KeyError:
          pass

    unresolved_plugins = plugin_names - set(plugins.keys())
    if unresolved_plugins:
      raise TaskError('Could not find requested plugins: %s' % list(unresolved_plugins))
    return plugins

  def log_zinc_file(self, analysis_file):
    self.context.log.debug('Calling zinc on: %s (%s)' %
                           (analysis_file,
                            hash_file(analysis_file).upper()
                            if os.path.exists(analysis_file)
                            else 'nonexistent'))
