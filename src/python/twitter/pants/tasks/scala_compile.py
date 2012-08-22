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
import textwrap

from collections import defaultdict

from twitter.common.collections import OrderedDict
from twitter.common.dirutil import safe_mkdir, safe_open, touch

from twitter.pants import is_scala, is_scalac_plugin
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

    option_group.add_option(mkflag("flatten"), mkflag("flatten", negate=True),
                            dest="scala_compile_flatten",
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Compile scala code for all dependencies in a "
                                 "single compilation.")

    option_group.add_option(mkflag("color"), mkflag("color", negate=True),
                            dest="scala_compile_color",
                            action="callback", callback=mkflag.set_bool,
                            help="[True] Enable color in logging.")

  def __init__(self, context, workdir=None):
    NailgunTask.__init__(self, context, workdir=context.config.get('scala-compile', 'nailgun_dir'))

    self._flatten = \
      context.options.scala_compile_flatten if context.options.scala_compile_flatten is not None else \
      context.config.getbool('scala-compile', 'default_to_flatten')

    # We use the scala_compile_color flag if it is explicitly set on the command line.
    self._color = \
      context.options.scala_compile_color if context.options.scala_compile_color is not None else \
      context.config.getbool('scala-compile', 'color', default=True)

    self._compile_profile = context.config.get('scala-compile', 'compile-profile')  # The target scala version.
    self._zinc_profile = context.config.get('scala-compile', 'zinc-profile')

    # All scala targets implicitly depend on the selected scala runtime.
    scaladeps = []
    for spec in context.config.getlist('scala-compile', 'scaladeps'):
      scaladeps.extend(context.resolve(spec))
    for target in context.targets(is_scala):
      target.update_dependencies(scaladeps)

    self._workdir = context.config.get('scala-compile', 'workdir') if workdir is None else workdir
    self._incremental_classes_dir = os.path.join(self._workdir, 'incremental.classes')
    self._flat_classes_dir = os.path.join(self._workdir, 'classes')
    self._analysis_cache_dir = os.path.join(self._workdir, 'analysis_cache')
    self._resources_dir = os.path.join(self._workdir, 'resources')

    self._main = context.config.get('scala-compile', 'main')

    self._args = context.config.getlist('scala-compile', 'args')
    self._jvm_args = context.config.getlist('scala-compile', 'jvm_args')
    if context.options.scala_compile_warnings:
      self._args.extend(context.config.getlist('scala-compile', 'warning_args'))
    else:
      self._args.extend(context.config.getlist('scala-compile', 'no_warning_args'))

    self._confs = context.config.getlist('scala-compile', 'confs')
    self._depfile_dir = os.path.join(self._workdir, 'depfiles')

  def product_type(self):
    return 'classes'

  def invalidate_for(self):
    return self._flatten

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

      with self.invalidated(scala_targets, invalidate_dependants=True) as invalidated:
        if self._flatten:
          # We must defer invalidation to zinc. If we exclude files from a repeat build, zinc will assume
          # the files were deleted and will nuke the corresponding class files. So we build all_targets
          # in one pass and let zinc figure it out.
          self.execute_single_compilation(invalidated.combined_all_versioned_targets(), cp, upstream_analysis_caches)
        else:
          # We must pass all targets,even valid ones, to execute_single_compilation(), so it can
          # track the deps and the upstream analysis map correctly.
          for vt in invalidated.all_versioned_targets():
            self.execute_single_compilation(vt, cp, upstream_analysis_caches)

  def execute_single_compilation(self, versioned_target_set, cp, upstream_analysis_caches):
    """Execute a single compilation, updating upstream_analysis_caches if needed."""
    if self._flatten:
      compilation_id = 'flat'
      output_dir = self._flat_classes_dir
    else:
      compilation_id = Target.maybe_readable_identify(versioned_target_set.targets)
      # Each compilation must output to its own directory, so zinc can then associate those with the appropriate
      # analysis caches of previous compilations. We then copy the results out to the real output dir.
      output_dir = os.path.join(self._incremental_classes_dir, compilation_id)

    depfile = os.path.join(self._depfile_dir, compilation_id) + '.dependencies'
    analysis_cache = os.path.join(self._analysis_cache_dir, compilation_id) + '.analysis_cache'

    safe_mkdir(output_dir)

    if not versioned_target_set.valid:
      with self.check_artifact_cache(versioned_target_set,
                                     build_artifacts=[output_dir, depfile, analysis_cache],
                                     artifact_root=self._workdir) as needs_building:
        if needs_building:
          self.context.log.info('Compiling targets %s' % versioned_target_set.targets)
          sources_by_target = self.calculate_sources(versioned_target_set.targets)
          if sources_by_target:
            sources = reduce(lambda all, sources: all.union(sources), sources_by_target.values())
            if not sources:
              touch(depfile)  # Create an empty depfile, since downstream code may assume that one exists.
              self.context.log.warn('Skipping scala compile for targets with no sources:\n  %s' %
                                    '\n  '.join(str(t) for t in sources_by_target.keys()))
            else:
              classpath = [jar for conf, jar in cp if conf in self._confs]
              result = self.compile(classpath, sources, output_dir, analysis_cache, upstream_analysis_caches, depfile)
              if result != 0:
                raise TaskError('%s returned %d' % (self._main, result))

    # Note that the following post-processing steps must happen even for valid targets.

    # Read in the deps created either just now or by a previous compiler run on these targets.
    if self.context.products.isrequired('classes'):
      self.context.log.debug('Reading dependencies from ' + depfile)
      deps = Dependencies(output_dir)
      deps.load(depfile)

      genmap = self.context.products.get('classes')

      for target, classes_by_source in deps.findclasses(versioned_target_set.targets).items():
        for source, classes in classes_by_source.items():
          genmap.add(source, output_dir, classes)
          genmap.add(target, output_dir, classes)

      # TODO(John Sirois): Map target.resources in the same way
      # Create and Map scala plugin info files to the owning targets.
      for target in versioned_target_set.targets:
        if is_scalac_plugin(target) and target.classname:
          basedir = self.write_plugin_info(target)
          genmap.add(target, basedir, [_PLUGIN_INFO_FILE])

    # Update the upstream analysis map.
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
    compiler_classpath = nailgun_profile_classpath(self, self._compile_profile)

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

    if len(analysis_map) > 0:
      args.extend([ '-analysis-map', ','.join(['%s:%s' % kv for kv in analysis_map.items()]) ])

    zinc_classpath = nailgun_profile_classpath(self, self._zinc_profile)
    zinc_jars = ScalaCompile.identify_zinc_jars(compiler_classpath, zinc_classpath)
    for (name, jarpath) in zinc_jars.items():  # The zinc jar names are also the flag names.
      args.extend(['-%s' % name, jarpath])

    args.extend([
      '-analysis-cache', analysis_cache,
      '-log-level', self.context.options.log_level or 'info',
      '-classpath', ':'.join(zinc_classpath + classpath),
      '-output-products', depfile,
      '-d', output_dir
    ])

    if not self._color:
      args.append('-no-color')

    args.extend(sources)

    self.context.log.debug('Executing: %s %s' % (self._main, ' '.join(args)))
    return self.runjava(self._main, classpath=zinc_classpath, args=args, jvmargs=self._jvm_args)

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
