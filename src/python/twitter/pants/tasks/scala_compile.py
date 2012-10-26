# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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

__author__ = 'John Sirois'

import os
import shutil
import textwrap

from collections import defaultdict
from xml.etree import ElementTree

from twitter.common.collections import OrderedDict
from twitter.common.contextutil import open_zip as open_jar, temporary_dir
from twitter.common.dirutil import safe_mkdir, safe_open, safe_rmtree

from twitter.pants import get_buildroot, is_scala, is_scalac_plugin
from twitter.pants.base.target import Target
from twitter.pants.targets.scala_library import ScalaLibrary
from twitter.pants.targets.scala_tests import ScalaTests
from twitter.pants.targets import resolve_target_sources
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.binary_utils import nailgun_profile_classpath
from twitter.pants.tasks.jvm_compiler_dependencies import Dependencies
from twitter.pants.tasks.nailgun_task import NailgunTask


# Well known metadata file required to register scalac plugins with nsc.
_PLUGIN_INFO_FILE = 'scalac-plugin.xml'


class ScalaCompile(NailgunTask):
  @staticmethod
  def _has_scala_sources(target):
    return isinstance(target, ScalaLibrary) or isinstance(target, ScalaTests)

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("warnings"), mkflag("warnings", negate=True),
                            dest="scala_compile_warnings", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Compile scala code with all configured warnings "
                                 "enabled.")

    option_group.add_option(mkflag("plugins"), dest="plugins", default=None,
      action="store", type="string",
      help="Use these scalac plugins. Default is set in pants.ini")

    option_group.add_option(mkflag("partition-size-hint"), dest="scala_compile_partition_size_hint",
      action="store", type="int", default=-1,
      help="Roughly how many source files to attempt to compile together. Set to a large number to compile " \
           "all sources together. Set this to 0 to compile target-by-target. Default is set in pants.ini.")

    option_group.add_option(mkflag("color"), mkflag("color", negate=True),
                            dest="scala_compile_color",
                            action="callback", callback=mkflag.set_bool,
                            help="[True] Enable color in logging.")

  def __init__(self, context, workdir=None):
    NailgunTask.__init__(self, context, workdir=context.config.get('scala-compile', 'nailgun_dir'))

    self._partition_size_hint = \
      context.options.scala_compile_partition_size_hint \
      if context.options.scala_compile_partition_size_hint != -1 else \
      context.config.getint('scala-compile', 'partition_size_hint')

    # We use the scala_compile_color flag if it is explicitly set on the command line.
    self._color = \
      context.options.scala_compile_color or context.config.getbool('scala-compile', 'color', default=True)

    self._compile_profile = context.config.get('scala-compile', 'compile-profile')  # The target scala version.
    self._zinc_profile = context.config.get('scala-compile', 'zinc-profile')
    plugins_profile = context.config.get('scala-compile', 'scalac-plugins-profile')

    self._zinc_classpath = nailgun_profile_classpath(self, self._zinc_profile)
    compiler_classpath = nailgun_profile_classpath(self, self._compile_profile)
    zinc_jars = ScalaCompile.identify_zinc_jars(compiler_classpath, self._zinc_classpath)
    self._zinc_jar_args = []
    for (name, jarpath) in zinc_jars.items():  # The zinc jar names are also the flag names.
      self._zinc_jar_args.extend(['-%s' % name, jarpath])

    self._plugin_jars = nailgun_profile_classpath(self, plugins_profile) if plugins_profile else []

    # All scala targets implicitly depend on the selected scala runtime.
    scaladeps = []
    for spec in context.config.getlist('scala-compile', 'scaladeps'):
      scaladeps.extend(context.resolve(spec))
    for target in context.targets(is_scala):
      target.update_dependencies(scaladeps)

    self._workdir = context.config.get('scala-compile', 'workdir') if workdir is None else workdir
    self._classes_dir = os.path.join(self._workdir, 'classes')
    self._analysis_cache_dir = os.path.join(self._workdir, 'analysis_cache')
    self._resources_dir = os.path.join(self._workdir, 'resources')

    self._main = context.config.get('scala-compile', 'main')

    self._args = context.config.getlist('scala-compile', 'args')
    self._jvm_args = context.config.getlist('scala-compile', 'jvm_args')
    if context.options.scala_compile_warnings:
      self._args.extend(context.config.getlist('scala-compile', 'warning_args'))
    else:
      self._args.extend(context.config.getlist('scala-compile', 'no_warning_args'))

    plugin_names = context.options.plugins.split(',') if context.options.plugins is not None \
      else context.config.getlist('scala-compile', 'scalac-plugins', default=[])

    plugin_args = dict(context.config.getlist('scala-compile', 'scalac-plugin-args', default=[]))

    active_plugins = ScalaCompile.find_plugins(plugin_names, self._plugin_jars)

    for name, jar in active_plugins.items():
      self._args.append('-Xplugin:%s' % jar)
      for arg in plugin_args.get(name, []):
        self._args.append('-P:%s:%s' % (name, arg))

    self._confs = context.config.getlist('scala-compile', 'confs')
    self._depfile_dir = os.path.join(self._workdir, 'depfiles')

    artifact_cache_spec = context.config.getlist('scala-compile', 'artifact_caches')
    self.setup_artifact_cache(artifact_cache_spec)

  def product_type(self):
    return 'classes'

  def can_dry_run(self):
    return True

  def execute(self, targets):
    scala_targets = filter(ScalaCompile._has_scala_sources, targets)
    if scala_targets:
      safe_mkdir(self._depfile_dir)
      safe_mkdir(self._analysis_cache_dir)

      # Map from output directory to { analysis_cache_dir, [ analysis_cache_file ]}
      upstream_analysis_caches = self.context.products.get('upstream')

      with self.context.state('classpath', []) as cp:
        for conf in self._confs:
          cp.insert(0, (conf, self._resources_dir))
          for jar in self._plugin_jars:
            cp.insert(0, (conf, jar))

      with self.invalidated(scala_targets, invalidate_dependants=True,
          partition_size_hint=self._partition_size_hint) as invalidation_check:
        for vt in invalidation_check.all_vts:
          if vt.valid:  # Don't compile, just post-process.
            self.post_process(vt, upstream_analysis_caches, split_artifact=False)
        for vt in invalidation_check.invalid_vts_partitioned:
          # Compile, using partitions for efficiency.
          self.execute_single_compilation(vt, cp, upstream_analysis_caches)
          if not self.dry_run:
            vt.update()

  def create_output_paths(self, targets):
    compilation_id = Target.maybe_readable_identify(targets)
    # Each compilation must output to its own directory, so zinc can then associate those with the appropriate
    # analysis caches of previous compilations.
    output_dir = os.path.join(self._classes_dir, compilation_id)

    depfile = os.path.join(self._depfile_dir, compilation_id) + '.dependencies'
    analysis_cache = os.path.join(self._analysis_cache_dir, compilation_id) + '.analysis_cache'
    return output_dir, depfile, analysis_cache

  def execute_single_compilation(self, versioned_target_set, cp, upstream_analysis_caches):
    """Execute a single compilation, updating upstream_analysis_caches if needed."""
    output_dir, depfile, analysis_cache = self.create_output_paths(versioned_target_set.targets)
    safe_mkdir(output_dir)

    if not versioned_target_set.valid:
      with self.check_artifact_cache(versioned_target_set,
                                     build_artifacts=[output_dir, depfile, analysis_cache]) as in_cache:
        if not in_cache:
          self.merge_artifact(versioned_target_set)  # Get what we can from previous builds.
          self.context.log.info('Compiling targets %s' % versioned_target_set.targets)
          sources_by_target = self.calculate_sources(versioned_target_set.targets)
          if sources_by_target:
            sources = reduce(lambda all, sources: all.union(sources), sources_by_target.values())
            if not sources:
              self.context.log.warn('Skipping scala compile for targets with no sources:\n  %s' %
                                    '\n  '.join(str(t) for t in sources_by_target.keys()))
            else:
              classpath = [jar for conf, jar in cp if conf in self._confs]
              result = self.compile(classpath, sources, output_dir, analysis_cache, upstream_analysis_caches, depfile)
              if result != 0:
                raise TaskError('%s returned %d' % (self._main, result))
    self.post_process(versioned_target_set, upstream_analysis_caches, split_artifact=True)

  # Post-processing steps that must happen even for valid targets.
  def post_process(self, vt, upstream_analysis_caches, split_artifact):
    output_dir, depfile, analysis_cache = self.create_output_paths(vt.targets)
    if not self.dry_run:
      # Read in the deps created either just now or by a previous compiler run on these targets.
      if os.path.exists(depfile):
        self.context.log.debug('Reading dependencies from ' + depfile)
        deps = Dependencies(output_dir)
        deps.load(depfile)

        if split_artifact:
          self.split_artifact(deps, vt)

        if self.context.products.isrequired('classes') :
          genmap = self.context.products.get('classes')
          for target, classes_by_source in deps.findclasses(vt.targets).items():
            for source, classes in classes_by_source.items():
              genmap.add(source, output_dir, classes)
              genmap.add(target, output_dir, classes)

          # TODO(John Sirois): Map target.resources in the same way
          # Create and Map scala plugin info files to the owning targets.
          for target in vt.targets:
            if is_scalac_plugin(target) and target.classname:
              basedir = self.write_plugin_info(target)
              genmap.add(target, basedir, [_PLUGIN_INFO_FILE])

    # Update the upstream analysis map.
    if os.path.exists(analysis_cache):
      analysis_cache_parts = os.path.split(analysis_cache)
      if not upstream_analysis_caches.has(output_dir):
        # A previous chunk might have already updated this. It is certainly possible for a later chunk to
        # independently depend on some target that a previous chunk already built.
        upstream_analysis_caches.add(output_dir, analysis_cache_parts[0], [ analysis_cache_parts[1] ])

    # Update the classpath.
    with self.context.state('classpath', []) as cp:
      for conf in self._confs:
        cp.insert(0, (conf, output_dir))

  def calculate_sources(self, targets):
    sources = defaultdict(set)
    def collect_sources(target):
      src = (os.path.join(target.target_base, source)
             for source in target.sources if source.endswith('.scala'))
      if src:
        sources[target].update(src)

        if (isinstance(target, ScalaLibrary) or isinstance(target, ScalaTests)) and (
            target.java_sources):
          sources[target].update(resolve_target_sources(target.java_sources, '.java'))

    for target in targets:
      collect_sources(target)
    return sources

  def compile(self, classpath, sources, output_dir, analysis_cache, upstream_analysis_caches, depfile):
    # To pass options to scalac simply prefix with -S.
    args = ['-S' + x for x in self._args]

    def analysis_cache_full_path(analysis_cache_product):
      # We expect the argument to be { analysis_cache_dir, [ analysis_cache_file ]}.
      if len(analysis_cache_product) != 1:
        raise TaskError('There can only be one analysis cache file per output directory')
      analysis_cache_dir, analysis_cache_files = analysis_cache_product.iteritems().next()
      if len(analysis_cache_files) != 1:
        raise TaskError('There can only be one analysis cache file per output directory')
      return os.path.join(analysis_cache_dir, analysis_cache_files[0])

    # Strings of <output dir>:<full path to analysis cache file for the classes in that dir>.
    analysis_map = \
      OrderedDict([ (k, analysis_cache_full_path(v)) for k, v in upstream_analysis_caches.itermappings() ])

    args.extend(self._zinc_jar_args)

    if len(analysis_map) > 0:
      args.extend([ '-analysis-map', ','.join(['%s:%s' % kv for kv in analysis_map.items()]) ])

    args.extend([
      '-analysis-cache', analysis_cache,
      '-log-level', self.context.options.log_level or 'info',
      '-classpath', ':'.join(self._zinc_classpath + classpath),
      '-output-products', depfile,
      '-d', output_dir
    ])

    if not self._color:
      args.append('-no-color')

    args.extend(sources)

    self.context.log.debug('Executing: %s %s' % (self._main, ' '.join(args)))
    return self.runjava(self._main, classpath=self._zinc_classpath, args=args, jvmargs=self._jvm_args)

  # Splits an artifact representing several targets into target-by-target artifacts.
  # Creates an output classes dir, a depfile and an analysis file for each target.
  # Note that it's not OK to create incomplete artifacts here: this is run *after* a zinc invocation,
  # and the expectation is that the result is complete.
  def split_artifact(self, deps, versioned_target_set):
    if len(versioned_target_set.targets) <= 1:
      return
    buildroot = get_buildroot()
    classes_by_source_by_target = deps.findclasses(versioned_target_set.targets)
    src_output_dir, _, src_analysis_cache = self.create_output_paths(versioned_target_set.targets)
    analysis_splits = []  # List of triples of (list of sources, destination output dir, destination analysis cache).
    for target in versioned_target_set.targets:
      classes_by_source = classes_by_source_by_target.get(target, {})
      dst_output_dir, dst_depfile, dst_analysis_cache = self.create_output_paths([target])
      safe_rmtree(dst_output_dir)
      safe_mkdir(dst_output_dir)

      sources = []
      dst_deps = Dependencies(dst_output_dir)

      for source, classes in classes_by_source.items():
        src = os.path.join(target.target_base, source)
        dst_deps.add(src, classes)
        source_abspath = os.path.join(buildroot, target.target_base, source)
        sources.append(source_abspath)
        for cls in classes:
          # Copy the class file.
          dst = os.path.join(dst_output_dir, cls)
          safe_mkdir(os.path.dirname(dst))
          os.link(os.path.join(src_output_dir, cls), dst)
      dst_deps.save(dst_depfile)
      analysis_splits.append((sources, dst_output_dir, dst_analysis_cache))

    # Use zinc to split the analysis files.
    if os.path.exists(src_analysis_cache):
      analysis_args = []
      analysis_args.extend(self._zinc_jar_args)
      analysis_args.extend([
        '-log-level', self.context.options.log_level or 'info',
        '-analysis',
        ])
      split_args = analysis_args + [
        '-cache', src_analysis_cache,
        '-split', ','.join(['{%s}:%s' % (':'.join(x[0]), x[2]) for x in analysis_splits]),
        ]
      if self.runjava(self._main, classpath=self._zinc_classpath, args=split_args, jvmargs=self._jvm_args):
        raise TaskError, 'zinc failed to split analysis files %s from %s' %\
                         (':'.join([x[2] for x in analysis_splits]), src_analysis_cache)

      # Now rebase the newly created analysis files.
      for split in analysis_splits:
        dst_analysis_cache = split[2]
        if os.path.exists(dst_analysis_cache):
          rebase_args = analysis_args + [
            '-cache', dst_analysis_cache,
            '-rebase', '%s:%s' % (src_output_dir, split[1]),
            ]
          if self.runjava(self._main, classpath=self._zinc_classpath, args=rebase_args, jvmargs=self._jvm_args):
            raise TaskError, 'In split_artifact: zinc failed to rebase analysis file %s' % dst_analysis_cache

  # Merges artifacts representing the individual targets in a VersionedTargetSet into one artifact for that set.
  # Creates an output classes dir, depfile and analysis file for the VersionedTargetSet.
  # Note that the merged artifact may be incomplete (e.g., if the previous build was aborted). That's OK: This
  # is run before a zinc invocation, so zinc will fill in what's missing. This exists only for efficiency, to
  # prevent zinc from doing superfluous work.
  def merge_artifact(self, versioned_target_set):
    if len(versioned_target_set.targets) <= 1:
      return

    with temporary_dir() as tmpdir:
      dst_output_dir, dst_depfile, dst_analysis_cache = self.create_output_paths(versioned_target_set.targets)
      safe_rmtree(dst_output_dir)
      safe_mkdir(dst_output_dir)
      src_analysis_caches = []

      analysis_args = []
      analysis_args.extend(self._zinc_jar_args)
      analysis_args.extend([
        '-log-level', self.context.options.log_level or 'info',
        '-analysis',
        ])

      # TODO: Do we actually need to merge deps? Zinc will stomp them anyway on success.
      dst_deps = Dependencies(dst_output_dir)

      for target in versioned_target_set.targets:
        src_output_dir, src_depfile, src_analysis_cache = self.create_output_paths([target])
        if os.path.exists(src_depfile):
          src_deps = Dependencies(src_output_dir)
          src_deps.load(src_depfile)
          dst_deps.merge(src_deps)

          classes_by_source = src_deps.findclasses([target]).get(target, {})
          for source, classes in classes_by_source.items():
            for cls in classes:
              src = os.path.join(src_output_dir, cls)
              dst = os.path.join(dst_output_dir, cls)
              # src may not exist if we aborted a build in the middle. That's OK: zinc will notice that
              # it's missing and rebuild it.
              # dst may already exist if we have overlapping targets. It's not a good idea
              # to have those, but until we enforce it, we must allow it here.
              if os.path.exists(src) and not os.path.exists(dst):
                # Copy the class file.
                safe_mkdir(os.path.dirname(dst))
                os.link(src, dst)

          # Use zinc to rebase a copy of the per-target analysis files prior to merging.
          if os.path.exists(src_analysis_cache):
            src_analysis_cache_tmp = \
              os.path.join(tmpdir, os.path.relpath(src_analysis_cache, self._analysis_cache_dir))
            shutil.copyfile(src_analysis_cache, src_analysis_cache_tmp)
            src_analysis_caches.append(src_analysis_cache_tmp)
            rebase_args = analysis_args + [
              '-cache', src_analysis_cache_tmp,
              '-rebase', '%s:%s' % (src_output_dir, dst_output_dir),
              ]
            if self.runjava(self._main, classpath=self._zinc_classpath, args=rebase_args, jvmargs=self._jvm_args):
              self.context.log.warn('In merge_artifact: zinc failed to rebase analysis file %s. ' \
              'Target may require a full rebuild.' % src_analysis_cache_tmp)

      dst_deps.save(dst_depfile)

      # Use zinc to merge the analysis files.
      merge_args = analysis_args + [
        '-cache', dst_analysis_cache,
        '-merge', ':'.join(src_analysis_caches),
      ]
      if self.runjava(self._main, classpath=self._zinc_classpath, args=merge_args, jvmargs=self._jvm_args):
        raise TaskError, 'zinc failed to merge analysis files %s to %s' % \
                         (':'.join(src_analysis_caches), dst_analysis_cache)


  def write_plugin_info(self, target):
    basedir = os.path.join(self._resources_dir, target.id)
    with safe_open(os.path.join(basedir, _PLUGIN_INFO_FILE), 'w') as f:
      f.write(textwrap.dedent('''
        <plugin>
          <name>%s</name>
          <classname>%s</classname>
        </plugin>
      ''' % (target.plugin, target.classname)).strip())
    return basedir

  # These are the names of the various jars zinc needs. They are, conveniently and non-coincidentally,
  # the names of the flags used to pass the jar locations to zinc.
  compiler_jar_names = [ 'scala-library', 'scala-compiler' ]  # Compiler version.
  zinc_jar_names = [ 'compiler-interface', 'sbt-interface' ]  # Other jars zinc needs to be pointed to.

  @staticmethod
  def identify_zinc_jars(compiler_classpath, zinc_classpath):
    """Find the named jars in the compiler and zinc classpaths.

    TODO: When profiles migrate to regular pants jar() deps instead of ivy.xml files we can make these
          mappings explicit instead of deriving them by jar name heuristics.
    """
    ret = OrderedDict()
    ret.update(ScalaCompile.identify_jars(ScalaCompile.compiler_jar_names, compiler_classpath))
    ret.update(ScalaCompile.identify_jars(ScalaCompile.zinc_jar_names, zinc_classpath))
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

  @staticmethod
  def find_plugins(plugin_names, plugin_jars):
    """Returns a map from plugin name to plugin jar."""
    plugin_names = set(plugin_names)
    plugins = {}
    # plugin_jars is the universe of all possible plugins and their transitive deps.
    # Here we select the ones to actually use.
    for jar in plugin_jars:
      with open_jar(jar, 'r') as jarfile:
        try:
          plugin_info_file = jarfile.open(_PLUGIN_INFO_FILE, 'r')  # Not a context manager, sadly.
          plugin_info = ElementTree.parse(plugin_info_file).getroot()
          plugin_info_file.close()
          if plugin_info.tag != 'plugin':
            raise TaskError, 'File %s in %s is not a valid scalac plugin descriptor' % (_PLUGIN_INFO_FILE, jar)
          name = plugin_info.find('name').text
          if name in plugin_names:
            if name in plugins:
              raise TaskError, 'Plugin %s defined in %s and in %s' % (name, plugins[name], jar)
            plugins[name] = jar
        except KeyError:
          pass

    unresolved_plugins = plugin_names - set(plugins.keys())
    if len(unresolved_plugins) > 0:
      raise TaskError, 'Could not find requested plugins: %s' % list(unresolved_plugins)
    return plugins

