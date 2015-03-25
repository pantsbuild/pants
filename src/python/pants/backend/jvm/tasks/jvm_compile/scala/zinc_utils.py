# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import textwrap
from contextlib import closing
from itertools import chain
from xml.etree import ElementTree

from pants.backend.jvm.scala.target_platform import TargetPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.hash_utils import hash_file
from pants.base.workunit import WorkUnit
from pants.util.contextutil import open_zip
from pants.util.dirutil import relativize_paths, safe_open


# Well known metadata file required to register scalac plugins with nsc.
_PLUGIN_INFO_FILE = 'scalac-plugin.xml'


# TODO: Fold this into ScalaCompile. Or at least the non-static parts.
# Right now it has to access so much state from that task that we have to pass it a reference back
# to the task.  This separation was primarily motivated  by the fact that we used to run Zinc for
# other reasons (such as split/merge/rebase of analysis files). But now ScalaCompile is the
# only client.
class ZincUtils(object):
  """Convenient wrapper around zinc invocations.

  Instances are immutable, and all methods are reentrant (assuming that the java_runner is).
  """

  class DepLookupError(AddressLookupError):
    """Thrown when a dependency can't be found."""
    pass

  _ZINC_MAIN = 'com.typesafe.zinc.Main'

  @classmethod
  def register_options(cls, register, register_jvm_tool):
    register_jvm_tool(register, 'scalac', default=TargetPlatform().default_compiler_specs)
    register_jvm_tool(register, 'zinc')
    register_jvm_tool(register, 'plugin-jars')


  def __init__(self, context, nailgun_task, jvm_options, color=True, log_level='info'):
    self.context = context
    self._nailgun_task = nailgun_task  # We run zinc on this task's behalf.
    self._jvm_options = jvm_options
    self._color = color
    self._log_level = log_level
    self._lazy_plugin_args = None

  @property
  def _zinc_classpath(self):
    return self._nailgun_task.tool_classpath('zinc')

  @property
  def _compiler_classpath(self):
    return self._nailgun_task.tool_classpath('scalac')

  def _zinc_jar_args(self):
    zinc_jars = self.identify_zinc_jars(self._zinc_classpath)
    # The zinc jar names are also the flag names.
    return (list(chain.from_iterable([['-%s' % name, jarpath]
                                     for (name, jarpath) in sorted(zinc_jars.items())])) +
            ['-scala-path', ':'.join(self._compiler_classpath)])

  def _plugin_args(self):
    if self._lazy_plugin_args is None:
      self._lazy_plugin_args = self._create_plugin_args()
    return self._lazy_plugin_args

  def _create_plugin_args(self):
    if not self._nailgun_task.get_options().plugins:
      return []

    plugin_args = self._nailgun_task.get_options().plugin_args
    active_plugins = self.find_plugins()
    ret = []
    for name, jar in active_plugins.items():
      ret.append('-S-Xplugin:%s' % jar)
      for arg in plugin_args.get(name, []):
        ret.append('-S-P:%s:%s' % (name, arg))
    return ret

  def plugin_jars(self):
    """The jars containing code for enabled plugins."""
    if self._nailgun_task.get_options().plugins:
      return self._nailgun_task.tool_classpath('plugin-jars')
    else:
      return []

  def platform_version_info(self):
    ret = []

    # Go through all the bootstrap tools required to compile.
    for toolname in ['scalac', 'zinc']:
      for target in self._nailgun_task.get_options()[toolname]:
        # Resolve to their actual targets.
        try:
          deps = self.context.resolve(target)
        except AddressLookupError as e:
          raise self.DepLookupError("{message}\n  specified by option --{tool} in scope {scope}."
                                    .format(message=e,
                                            tool=toolname,
                                            scope=self._nailgun_task.options_scope))

        for lib in (t for t in deps if isinstance(t, JarLibrary)):
          for jar in lib.jar_dependencies:
            ret.append(jar.cache_key())

    # We must invalidate on the set of plugins and their settings.
    ret.extend(self._plugin_args())
    return ret

  @staticmethod
  def relativize_classpath(classpath):
    return relativize_paths(classpath, get_buildroot())

  def compile(self, extra_args, classpath, sources, output_dir,
              analysis_file, upstream_analysis_files):

    # We add compiler_classpath to ensure the scala-library jar is on the classpath.
    # TODO: This also adds the compiler jar to the classpath, which compiled code shouldn't
    # usually need. Be more selective?
    relativized_classpath = self.relativize_classpath(self._compiler_classpath + classpath)

    args = []

    args.extend([
      '-log-level', self._log_level,
      '-analysis-cache', analysis_file,
      '-classpath', ':'.join(relativized_classpath),
      '-d', output_dir
    ])
    if not self._color:
      args.append('-no-color')
    if not self._nailgun_task.get_options().name_hashing:
      args.append('-no-name-hashing')

    args.extend(self._zinc_jar_args())
    args += self._plugin_args()
    if upstream_analysis_files:
      args.extend(
        ['-analysis-map', ','.join(['%s:%s' % kv for kv in upstream_analysis_files.items()])])

    args += extra_args

    args.extend(sources)

    self.log_zinc_file(analysis_file)
    if self._nailgun_task.runjava(classpath=self._zinc_classpath,
                                  main=self._ZINC_MAIN,
                                  jvm_options=self._jvm_options,
                                  args=args,
                                  workunit_name='zinc',
                                  workunit_labels=[WorkUnit.COMPILER]):
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

  @classmethod
  def identify_zinc_jars(cls, zinc_classpath):
    """Find the named jars in the zinc classpath.

    TODO: Make these mappings explicit instead of deriving them by jar name heuristics.
    """
    jars_by_name = {}
    jars_and_filenames = [(x, os.path.basename(x)) for x in zinc_classpath]

    for name in cls.ZINC_JAR_NAMES:
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

  def find_plugins(self):
    """Returns a map from plugin name to plugin jar."""
    # Allow multiple flags and also comma-separated values in a single flag.
    plugin_names = set([p for val in self._nailgun_task.get_options().plugins
                          for p in val.split(',')])
    plugins = {}
    buildroot = get_buildroot()
    for jar in self.plugin_jars():
      with open_zip(jar, 'r') as jarfile:
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
