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

from twitter.common.collections import OrderedDict
from twitter.common.dirutil import safe_mkdir, safe_open, touch

from twitter.pants import is_scala, is_scalac_plugin
from twitter.pants.targets.scala_library import ScalaLibrary
from twitter.pants.targets.scala_tests import ScalaTests
from twitter.pants.targets import resolve_target_sources
from twitter.pants.targets.internal import InternalTarget
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
    self._depemitter_profile = context.config.get('scala-compile', 'dependencies-plugin-profile')

    # All scala targets implicitly depend on the selected scala runtime.
    scaladeps = []
    for spec in context.config.getlist('scala-compile', 'scaladeps'):
      scaladeps.extend(context.resolve(spec))
    for target in context.targets(is_scala):
      target.update_dependencies(scaladeps)

    if workdir is None:
      workdir = context.config.get('scala-compile', 'workdir')
    self._incremental_classes_dir = os.path.join(workdir, 'incremental.classes')
    self._classes_dir = os.path.join(workdir, 'classes')
    self._analysis_cache_dir = os.path.join(workdir, 'analysis_cache')
    self._resources_dir = os.path.join(workdir, 'resources')

    self._main = context.config.get('scala-compile', 'main')

    self._args = context.config.getlist('scala-compile', 'args')
    self._jvm_args = context.config.getlist('scala-compile', 'jvm_args')
    if context.options.scala_compile_warnings:
      self._args.extend(context.config.getlist('scala-compile', 'warning_args'))
    else:
      self._args.extend(context.config.getlist('scala-compile', 'no_warning_args'))

    self._confs = context.config.getlist('scala-compile', 'confs')
    self._depfile_dir = os.path.join(workdir, 'depfiles')
    self._deps = Dependencies(self._classes_dir)

  def invalidate_for(self):
    return [self._flatten]

  def execute(self, targets):
    scala_targets = filter(ScalaCompile._has_scala_sources, reversed(InternalTarget.sort_targets(targets)))
    if scala_targets:
      safe_mkdir(self._depfile_dir)
      safe_mkdir(self._analysis_cache_dir)

      # Map from output directory to { analysis_cache_dir, [ analysis_cache_file ]}
      upstream_analysis_caches = self.context.products.get('upstream')

      with self.context.state('classpath', []) as cp:
        for conf in self._confs:
          cp.insert(0, (conf, self._resources_dir))

      if self._flatten:
        self.execute_single_compilation(scala_targets, cp, upstream_analysis_caches)
      else:
        for target in scala_targets:
          self.execute_single_compilation([target], cp, upstream_analysis_caches)


      # Now we can add the global output dir, so that subsequent goals can see it.
      with self.context.state('classpath', []) as cp:
        for conf in self._confs:
          cp.insert(0, (conf, self._classes_dir))

      if self.context.products.isrequired('classes'):
        genmap = self.context.products.get('classes')

        # Map generated classes to the owning targets and sources.
        for target, classes_by_source in self._deps.findclasses(scala_targets).items():
          for source, classes in classes_by_source.items():
            genmap.add(source, self._classes_dir, classes)
            genmap.add(target, self._classes_dir, classes)

        # TODO(John Sirois): Map target.resources in the same way
        # Create and Map scala plugin info files to the owning targets.
        for target in scala_targets:
          if is_scalac_plugin(target) and target.classname:
            basedir = self.write_plugin_info(target)
            genmap.add(target, basedir, [_PLUGIN_INFO_FILE])

  def execute_single_compilation(self, scala_targets, cp, upstream_analysis_caches):
    """Execute a single compilation, updating upstream_analysis_caches if needed."""
    self.context.log.info('Compiling targets %s' % str(scala_targets))

    if self._flatten:
      compilation_id = 'flat'
      output_dir = self._classes_dir
    else:
      compilation_id = Target.maybe_readable_identify(scala_targets)
      # Each compilation must output to its own directory, so zinc can then associate those with the appropriate
      # analysis caches of previous compilations. We then copy the results out to the real output dir.
      output_dir = os.path.join(self._incremental_classes_dir, compilation_id)

    depfile = os.path.join(self._depfile_dir, compilation_id) + '.dependencies'
    analysis_cache = os.path.join(self._analysis_cache_dir, compilation_id) + '.analysis_cache'

    # Note that we invalidate globally, i.e., if any target has changed then we pass them all on to zinc for
    # dependency analysis. This is because if we exclude files from a repeat build, zinc will assume
    # the files were deleted and will nuke the corresponding class files.

    with self.changed(scala_targets, invalidate_dependants=True,
                      invalidate_globally=True) as changed_targets:
      sources_by_target = self.calculate_sources(changed_targets)
      if sources_by_target:
        sources = reduce(lambda all, sources: all.union(sources), sources_by_target.values())
        if not sources:
          # Create an empty depfile, since downstream code may assume that a depfile exists.
          touch(depfile)
          self.context.log.warn('Skipping scala compile for targets with no sources:\n  %s' %
                                '\n  '.join(str(t) for t in sources_by_target.keys()))
        else:
          classpath = [jar for conf, jar in cp if conf in self._confs]
          result = self.compile(classpath, sources, output_dir, analysis_cache, upstream_analysis_caches, depfile)
          if result != 0:
            raise TaskError('%s returned %d' % (self._main, result))
          if output_dir != self._classes_dir:
            # Link class files emitted in this compilation into the central classes dir.
            self.link_all(output_dir, self._classes_dir)

    # Read in the deps created either just now or by a previous compiler run on these targets.
    self.context.log.debug('Reading dependencies from ' + depfile)
    deps = Dependencies(output_dir)
    deps.load(depfile)
    self._deps.merge(deps)

    analysis_cache_parts = os.path.split(analysis_cache)
    if not upstream_analysis_caches.has(output_dir):
      # A previous chunk might have already updated this. It is certainly possible for a later chunk to
      # independently depend on some target that a previous chunk already built.
      upstream_analysis_caches.add(output_dir, analysis_cache_parts[0], [ analysis_cache_parts[1] ])
    return compilation_id

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
    safe_mkdir(output_dir)
    compiler_classpath = nailgun_profile_classpath(self, self._compile_profile)
    compiler_args = []

    # TODO(John Sirois): separate compiler profile from runtime profile
    compiler_args.extend([
      # Support for outputting a dependencies file of source -> class
      '-Xplugin:%s' % self.get_depemitter_plugin(),
      '-P:depemitter:file:%s' % depfile
    ])
    compiler_args.extend(self._args)

    # To pass options to scalac simply prefix with -S.
    args = ['-S' + x for x in compiler_args]

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
    upstream_classes_dirs = analysis_map.keys()

    zinc_classpath = nailgun_profile_classpath(self, self._zinc_profile)
    zinc_jars = ScalaCompile.identify_zinc_jars(compiler_classpath, zinc_classpath)
    for (name, jarpath) in zinc_jars.items():  # The zinc jar names are also the flag names.
      args.extend(['-%s' % name, jarpath])

    args.extend([
      '-analysis-cache', analysis_cache,
      '-log-level', self.context.options.log_level or 'info',
      '-classpath', ':'.join(zinc_classpath + classpath + upstream_classes_dirs),
      '-d', output_dir
    ])

    if not self._color:
      args.append('-no-color')

    args.extend(sources)

    self.context.log.debug('Executing: %s %s' % (self._main, ' '.join(args)))
    return self.runjava(self._main, classpath=zinc_classpath, args=args, jvmargs=self._jvm_args)

  def get_depemitter_plugin(self):
    depemitter_classpath = nailgun_profile_classpath(self, self._depemitter_profile)
    depemitter_jar = depemitter_classpath.pop()
    if depemitter_classpath:
      raise TaskError('Expected only 1 jar for the depemitter plugin, '
                      'found these extra: ' % depemitter_classpath)
    return depemitter_jar

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

  def link_all(self, srcdir, dstdir):
    safe_mkdir(dstdir)
    for (dirpath, dirnames, filenames) in os.walk(srcdir):
      for d in [os.path.join(dirpath, x) for x in dirnames]:
        dir = os.path.join(dstdir, os.path.relpath(d, srcdir))
        if not os.path.isdir(dir):
          os.mkdir(dir)
      for f in [os.path.join(dirpath, x) for x in filenames]:
        outfile = os.path.join(dstdir, os.path.relpath(f, srcdir))
        if os.path.exists(outfile):
          os.unlink(outfile)
        os.link(f, outfile)
