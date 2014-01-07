# ==================================================================================================
# Copyright 2013 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import os
import shutil
import textwrap

from contextlib import closing
from itertools import chain
from xml.etree import ElementTree

from twitter.common.collections import OrderedDict
from twitter.common.contextutil import open_zip as open_jar, temporary_dir
from twitter.common.dirutil import  safe_open

from twitter.pants.base.build_environment import get_buildroot
from twitter.pants.base.hash_utils import hash_file
from twitter.pants.base.workunit import WorkUnit
from twitter.pants.tasks import TaskError


# Well known metadata file required to register scalac plugins with nsc.
from twitter.pants.tasks.scala.zinc_analysis import Analysis

_PLUGIN_INFO_FILE = 'scalac-plugin.xml'

class ZincUtils(object):
  """Convenient wrapper around zinc invocations.

  Instances are immutable, and all methods are reentrant (assuming that the java_runner is).
  """
  def __init__(self, context, nailgun_task, jvm_options, color, bootstrap_utils):
    self.context = context
    self._nailgun_task = nailgun_task  # We run zinc on this task's behalf.
    self._jvm_options = jvm_options
    self._color = color
    self._bootstrap_utils = bootstrap_utils

    self._pants_home = get_buildroot()

    # The target scala version.
    self._compile_bootstrap_key = 'scalac'
    compile_bootstrap_tools = context.config.getlist('scala-compile', 'compile-bootstrap-tools',
                                                     default=[':scala-compile-2.9.3'])
    self._bootstrap_utils.register_jvm_build_tools(self._compile_bootstrap_key, compile_bootstrap_tools)

    # The zinc version (and the scala version it needs, which may differ from the target version).
    self._zinc_bootstrap_key = 'zinc'
    zinc_bootstrap_tools = context.config.getlist('scala-compile', 'zinc-bootstrap-tools', default=[':zinc'])
    self._bootstrap_utils.register_jvm_build_tools(self._zinc_bootstrap_key, zinc_bootstrap_tools)

    # Compiler plugins.
    plugins_bootstrap_tools = context.config.getlist('scala-compile', 'scalac-plugin-bootstrap-tools',
                                                     default=[])
    if plugins_bootstrap_tools:
      self._plugins_bootstrap_key = 'plugins'
      self._bootstrap_utils.register_jvm_build_tools(self._plugins_bootstrap_key, plugins_bootstrap_tools)
    else:
      self._plugins_bootstrap_key = None

    self._main = context.config.get('scala-compile', 'main')

    # For localizing/relativizing analysis files.
    self._java_home = context.java_home
    self._ivy_home = context.ivy_home

  @property
  def _zinc_classpath(self):
    return self._bootstrap_utils.get_jvm_build_tools_classpath(self._zinc_bootstrap_key)

  @property
  def _compiler_classpath(self):
    return self._bootstrap_utils.get_jvm_build_tools_classpath(self._compile_bootstrap_key)

  @property
  def _plugin_jars(self):
    if self._plugins_bootstrap_key:
      return self._bootstrap_utils.get_jvm_build_tools_classpath(self._plugins_bootstrap_key)
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
    if self.context.options.plugins is not None:
      plugin_names = [p for val in self.context.options.plugins for p in val.split(',')]
    else:
      plugin_names = self.context.config.getlist('scala-compile', 'scalac-plugins', default=[])

    plugin_args = self.context.config.getdict('scala-compile', 'scalac-plugin-args', default={})
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

  def run_zinc(self, args, workunit_name='zinc', workunit_labels=None):
    zinc_args = [
      '-log-level', self.context.options.log_level or 'info',
    ]
    if not self._color:
      zinc_args.append('-no-color')
    zinc_args.extend(self._zinc_jar_args)
    zinc_args.extend(args)
    return self._nailgun_task.runjava_indivisible(self._main,
                                                  classpath=self._zinc_classpath,
                                                  args=zinc_args,
                                                  jvm_options=self._jvm_options,
                                                  workunit_name=workunit_name,
                                                  workunit_labels=workunit_labels)

  def compile(self, opts, classpath, sources, output_dir, analysis_file, upstream_analysis_files):
    args = list(opts)  # Make a copy

    args.extend(self._plugin_args())

    if len(upstream_analysis_files):
      args.extend(
        ['-analysis-map', ','.join(['%s:%s' % kv for kv in upstream_analysis_files.items()])])

    args.extend([
      '-analysis-cache', analysis_file,
      # We add compiler_classpath to ensure the scala-library jar is on the classpath.
      # TODO: This also adds the compiler jar to the classpath, which compiled code shouldn't
      # usually need. Be more selective?
      '-classpath', ':'.join(self._compiler_classpath + classpath),
      '-d', output_dir
    ])
    args.extend(sources)
    self.log_zinc_file(analysis_file)
    return self.run_zinc(args, workunit_labels=[WorkUnit.COMPILER])

  IVY_HOME_PLACEHOLDER = '/IVY_HOME_PLACEHOLDER'
  PANTS_HOME_PLACEHOLDER = '/PANTS_HOME_PLACEHOLDER'

  def relativize_analysis_file(self, src, dst):
    # Make an analysis cache portable. Work on a tmpfile, for safety.
    #
    # NOTE: We can't port references to deps on the Java home. This is because different JVM
    # implementations on different systems have different structures, and there's not
    # necessarily a 1-1 mapping between Java jars on different systems. Instead we simply
    # drop those references from the analysis file.
    #
    # In practice the JVM changes rarely, and it should be fine to require a full rebuild
    # in those rare cases.
    with temporary_dir() as tmp_analysis_dir:
      tmp_analysis_file = os.path.join(tmp_analysis_dir, 'analysis.relativized')

      rebasings = [
        (self._java_home, None),
        (self._ivy_home, ZincUtils.IVY_HOME_PLACEHOLDER),
        (self._pants_home, ZincUtils.PANTS_HOME_PLACEHOLDER),
      ]
      Analysis.rebase(src, tmp_analysis_file, rebasings)
      shutil.move(tmp_analysis_file, dst)

  def localize_analysis_file(self, src, dst):
    with temporary_dir() as tmp_analysis_dir:
      tmp_analysis_file = os.path.join(tmp_analysis_dir, 'analysis')
      rebasings = [
        (ZincUtils.IVY_HOME_PLACEHOLDER, self._ivy_home),
        (ZincUtils.PANTS_HOME_PLACEHOLDER, self._pants_home),
      ]
      Analysis.rebase(src, tmp_analysis_file, rebasings)
      shutil.move(tmp_analysis_file, dst)

  @staticmethod
  def write_plugin_info(resources_dir, target):
    basedir = os.path.join(resources_dir, target.id)
    with safe_open(os.path.join(basedir, _PLUGIN_INFO_FILE), 'w') as f:
      f.write(textwrap.dedent('''
        <plugin>
          <name>%s</name>
          <classname>%s</classname>
        </plugin>
      ''' % (target.plugin, target.classname)).strip())
    return basedir, _PLUGIN_INFO_FILE

  # These are the names of the various jars zinc needs. They are, conveniently and
  # non-coincidentally, the names of the flags used to pass the jar locations to zinc.
  zinc_jar_names = ['compiler-interface', 'sbt-interface' ]

  @staticmethod
  def identify_zinc_jars(zinc_classpath):
    """Find the named jars in the zinc classpath.

    TODO: When profiles migrate to regular pants jar() deps instead of ivy.xml files we can
          make these mappings explicit instead of deriving them by jar name heuristics.
    """
    ret = OrderedDict()
    ret.update(ZincUtils.identify_jars(ZincUtils.zinc_jar_names, zinc_classpath))
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
            plugins[name] = os.path.relpath(jar, self._pants_home)
        except KeyError:
          pass

    unresolved_plugins = plugin_names - set(plugins.keys())
    if len(unresolved_plugins) > 0:
      raise TaskError('Could not find requested plugins: %s' % list(unresolved_plugins))
    return plugins

  def log_zinc_file(self, analysis_file):
    self.context.log.debug('Calling zinc on: %s (%s)' % (analysis_file, hash_file(analysis_file).upper() if os.path.exists(analysis_file) else 'nonexistent'))

  @staticmethod
  def is_nonempty_analysis(path):
    """Returns true iff path exists and points to a non-empty analysis."""
    if not os.path.exists(path):
      return False
    empty_prefix = 'products:\n0 items\n'
    with open(path, 'r') as infile:
      prefix = infile.read(len(empty_prefix))
    return prefix != empty_prefix
