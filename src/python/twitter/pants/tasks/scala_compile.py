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

__author__ = 'Benjy Weinberger'

import os
import shutil

from collections import defaultdict, namedtuple

from twitter.common.collections.orderedset import OrderedSet
from twitter.common.contextutil import  temporary_dir
from twitter.common.dirutil import safe_mkdir, safe_rmtree

from twitter.pants import  is_scalac_plugin
from twitter.pants.base.target import Target
from twitter.pants.targets.scala_library import ScalaLibrary
from twitter.pants.targets.scala_tests import ScalaTests
from twitter.pants.targets import resolve_target_sources
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.jvm_compiler_dependencies import Dependencies
from twitter.pants.tasks.jvm_dependency_cache import JvmDependencyCache
from twitter.pants.tasks.nailgun_task import NailgunTask
from twitter.pants.tasks.zinc_utils import ZincUtils


# There are two versions of the zinc analysis file: The one zinc creates on compilation, which
# contains full paths and is therefore not portable, and the portable version, that we create by rebasing
# the full path prefixes to placeholders. We refer to this as "relativizing" the analysis file.
# The inverse, replacing placeholders with full path prefixes so we can use the file again when compiling,
# is referred to as "localizing" the analysis file.
#
# This is necessary only when using the artifact cache: We must relativize before uploading to the cache,
# and localize after pulling from the cache.

def _portable(analysis_file):
  """Returns the path to the portable version of the zinc analysis file."""
  return analysis_file + '.portable'


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
      action="append", help="Use these scalac plugins. Default is set in pants.ini.")

    option_group.add_option(mkflag("partition-size-hint"), dest="scala_compile_partition_size_hint",
      action="store", type="int", default=-1,
      help="Roughly how many source files to attempt to compile together. Set to a large number to compile " \
           "all sources together. Set this to 0 to compile target-by-target. Default is set in pants.ini.")

    option_group.add_option(mkflag("color"), mkflag("color", negate=True),
                            dest="scala_compile_color",
                            action="callback", callback=mkflag.set_bool,
                            help="[True] Enable color in logging.")
    JvmDependencyCache.setup_parser(option_group, args, mkflag)


  def __init__(self, context, workdir=None):
    NailgunTask.__init__(self, context, workdir=context.config.get('scala-compile', 'nailgun_dir'))

    # Set up the zinc utils.
    color = context.options.scala_compile_color or \
            context.config.getbool('scala-compile', 'color', default=True)

    self._zinc_utils = ZincUtils(context=context, java_runner=self.runjava, color=color)

    # The rough number of source files to build in each compiler pass.
    self._partition_size_hint = \
      context.options.scala_compile_partition_size_hint \
      if context.options.scala_compile_partition_size_hint != -1 else \
      context.config.getint('scala-compile', 'partition_size_hint')

    # Set up dep checking if needed.
    if context.options.scala_check_missing_deps:
      JvmDependencyCache.init_product_requirements(self)

    # Various output directories.
    workdir = context.config.get('scala-compile', 'workdir') if workdir is None else workdir
    self._resources_dir = os.path.join(workdir, 'resources')
    self._classes_dir_base = os.path.join(workdir, 'classes')
    self._depfiles_base = os.path.join(workdir, 'depfiles')
    self._analysis_files_base = os.path.join(workdir, 'analysis_cache')

    # The ivy confs for which we're building.
    self._confs = context.config.getlist('scala-compile', 'confs')

    # The artifact cache to read from/write to.
    artifact_cache_spec = context.config.getlist('scala-compile', 'artifact_caches')
    self.setup_artifact_cache(artifact_cache_spec)

  def product_type(self):
    return 'classes'

  def can_dry_run(self):
    return True

  def _output_paths(self, targets):
    """Returns the full paths to the classes dir, depfile and analysis file for the given target set."""
    compilation_id = Target.maybe_readable_identify(targets)
    # Each compilation must output to its own directory, so zinc can then associate those with the appropriate
    # analysis files of previous compilations.
    classes_dir = os.path.join(self._classes_dir_base, compilation_id)

    depfile = os.path.join(self._depfiles_base, compilation_id) + '.dependencies'
    analysis_file = os.path.join(self._analysis_files_base, compilation_id) + '.analysis'
    return classes_dir, depfile, analysis_file

  def execute(self, targets):
    scala_targets = filter(ScalaCompile._has_scala_sources, targets)
    if not scala_targets:
      return

    safe_mkdir(self._classes_dir_base)
    safe_mkdir(self._depfiles_base)
    safe_mkdir(self._analysis_files_base)

    # Get the classpath generated by upstream JVM tasks (including previous calls to this execute()).
    with self.context.state('classpath', []) as cp:
      self._add_globally_required_classpath_entries(cp)

      with self.invalidated_with_artifact_cache_check(
          scala_targets,
          invalidate_dependents=True,
          partition_size_hint=self._partition_size_hint) as (invalidation_check, cached_vts):
        # Localize the analysis files we read from the artifact cache.
        self._localize_portable_artifact_files(cached_vts)
        # Compile partitions one by one.
        self._compile_all(invalidation_check.invalid_vts_partitioned, scala_targets, cp)

      # Post-processing we perform for all targets, whether they needed compilation or not.
      for target in scala_targets:
        self._post_process(target, cp)

    # Check for missing dependencies.
    all_analysis_files = set()
    for target in scala_targets:
      _, _, analysis_file = self._output_paths([target])
      if os.path.exists(analysis_file):
        all_analysis_files.add(analysis_file)
    deps_cache = JvmDependencyCache(self.context, scala_targets, all_analysis_files)
    deps_cache.check_undeclared_dependencies()

  def _add_globally_required_classpath_entries(self, cp):
    # Add classpath entries necessary both for our compiler calls and for downstream JVM tasks.
    for conf in self._confs:
      cp.insert(0, (conf, self._resources_dir))
      for jar in self._zinc_utils.plugin_jars():
        cp.insert(0, (conf, jar))

  def _localize_portable_artifact_files(self, vts):
    # Localize the analysis files we read from the artifact cache.
    for vt in vts:
      _, _, analysis_file = self._output_paths(vt.targets)
      if self._zinc_utils.localize_analysis_file(_portable(analysis_file), analysis_file):
        self.context.log.warn('Zinc failed to localize analysis file: %s. '\
                              'Incremental rebuild of that target may not be possible.' % analysis_file)

  def _compute_upstream(self, scala_targets, cp, vts):
    # Returns the upstream analysis files and classpath for all targets in vts.
    upstream_analysis_files = {}
    upstream_classpath = OrderedSet([jar for conf, jar in cp if conf in self._confs])

    def add_upstream(target):
      classes_dir, _, analysis_file = self._output_paths([target])
      if os.path.isdir(classes_dir):
        upstream_classpath.add(classes_dir)
        if os.path.isfile(analysis_file):
          upstream_analysis_files[classes_dir] = analysis_file

    # Get our upstream by walking our scala dependencies, ignoring the targets we're currently compiling.
    all_other_targets = set(scala_targets).difference(vts.targets)
    for target in vts.targets:
      target.walk(add_upstream, lambda t: t in all_other_targets)

    return upstream_analysis_files, list(upstream_classpath)

  def _compile_all(self, vtslist, scala_targets, cp):
    for vts in vtslist:
      if not self.dry_run:
        upstream_analysis_files, upstream_classpath = self._compute_upstream(scala_targets, cp, vts)
        # Actually compile. TODO: self.compile() can be a unit of concurrent execution.
        self._compile(vts, upstream_classpath, upstream_analysis_files)
        vts.update()

  def _compile(self, versioned_target_set, classpath, upstream_analysis_files):
    """Actually compile some targets.

    May be invoked concurrently on independent target sets.

    Postcondition: The individual targets in versioned_target_set are up-to-date, as if each
                   were compiled individually.
    """
    # Note: We actually compile all the targets in the set in a single zinc call, because
    # compiler invocation overhead is high, but this fact is not exposed outside this method.
    classes_dir, depfile, analysis_file = self._output_paths(versioned_target_set.targets)
    safe_mkdir(classes_dir)

    # Get anything we have from previous builds.
    self._merge_artifact(versioned_target_set)

    # Compute the sources we need to compile.
    sources_by_target = ScalaCompile._calculate_sources(versioned_target_set.targets)

    if sources_by_target:
      sources = reduce(lambda all, sources: all.union(sources), sources_by_target.values())
      if not sources:
        self.context.log.warn('Skipping scala compile for targets with no sources:\n  %s' %
                              '\n  '.join(str(t) for t in sources_by_target.keys()))
      else:
        # Invoke the compiler.
        self.context.log.info('Compiling targets %s' % versioned_target_set.targets)
        if self._zinc_utils.compile(classpath, sources, classes_dir, analysis_file,
                                    upstream_analysis_files, depfile):
          raise TaskError('Compile failed.')

        # Read in the deps we just created.
        self.context.log.debug('Reading dependencies from ' + depfile)
        deps = Dependencies(classes_dir)
        deps.load(depfile)

        # Split the artifact into per-target artifacts.
        self._split_artifact(deps, versioned_target_set)

        # Write to artifact cache, if needed.
        for vt in versioned_target_set.versioned_targets:
          vt_classes_dir, vt_depfile, vt_analysis_file = self._output_paths(vt.targets)
          vt_portable_analysis_file = _portable(vt_analysis_file)
          if self._artifact_cache and self.context.options.write_to_artifact_cache:
            # Relativize the analysis.
            # TODO: Relativize before splitting? This will require changes to Zinc, which currently
            # eliminates paths it doesn't recognize (including our placeholders) when splitting.
            if self._zinc_utils.relativize_analysis_file(vt_analysis_file, vt_portable_analysis_file):
              raise TaskError('Zinc failed to relativize analysis file: %s' % vt_analysis_file)
            # Write the per-target artifacts to the cache.
            artifacts = [vt_classes_dir, vt_depfile, vt_portable_analysis_file]
            self.update_artifact_cache(vt, artifacts)
          else:
            safe_rmtree(vt_portable_analysis_file)  # Don't leave cruft lying around.

  def _post_process(self, target, cp):
    """Must be called on all targets, whether they needed compilation or not."""
    classes_dir, depfile, _ = self._output_paths([target])

    # Update the classpath, for the benefit of tasks downstream from us.
    if os.path.exists(classes_dir):
      for conf in self._confs:
        cp.insert(0, (conf, classes_dir))

    # Make note of the classes generated by this target.
    if os.path.exists(depfile) and self.context.products.isrequired('classes'):
      self.context.log.debug('Reading dependencies from ' + depfile)
      deps = Dependencies(classes_dir)
      deps.load(depfile)
      genmap = self.context.products.get('classes')
      for classes_by_source in deps.findclasses([target]).values():
        for source, classes in classes_by_source.items():
          genmap.add(source, classes_dir, classes)
          genmap.add(target, classes_dir, classes)

          # TODO(John Sirois): Map target.resources in the same way
          # Create and Map scala plugin info files to the owning targets.
        if is_scalac_plugin(target) and target.classname:
          basedir, plugin_info_file = self._zinc_utils.write_plugin_info(self._resources_dir, target)
          genmap.add(target, basedir, [plugin_info_file])

  def _merge_artifact(self, versioned_target_set):
    """Merges artifacts representing the individual targets in a VersionedTargetSet into one artifact for that set.
    Creates an output classes dir, depfile and analysis file for the VersionedTargetSet.
    Note that the merged artifact may be incomplete (e.g., if we have no previous artifacts for some of the
    individual targets). That's OK: We run this right before we invoke zinc, which will fill in what's missing.
    This method is not required for correctness, only for efficiency: it can prevent zinc from doing superfluous work.

    NOTE: This method is reentrant.
    """
    if len(versioned_target_set.targets) <= 1:
      return  # Nothing to do.

    with temporary_dir() as tmpdir:
      dst_classes_dir, dst_depfile, dst_analysis_file = self._output_paths(versioned_target_set.targets)
      safe_rmtree(dst_classes_dir)
      safe_mkdir(dst_classes_dir)
      src_analysis_files = []

      # TODO: Do we actually need to merge deps? Zinc will stomp them anyway on success.
      dst_deps = Dependencies(dst_classes_dir)

      for target in versioned_target_set.targets:
        src_classes_dir, src_depfile, src_analysis_file = self._output_paths([target])
        if os.path.exists(src_depfile):
          src_deps = Dependencies(src_classes_dir)
          src_deps.load(src_depfile)
          dst_deps.merge(src_deps)

          classes_by_source = src_deps.findclasses([target]).get(target, {})
          for source, classes in classes_by_source.items():
            for cls in classes:
              src = os.path.join(src_classes_dir, cls)
              dst = os.path.join(dst_classes_dir, cls)
              # src may not exist if we aborted a build in the middle. That's OK: zinc will notice that
              # it's missing and rebuild it.
              # dst may already exist if we have overlapping targets. It's not a good idea
              # to have those, but until we enforce it, we must allow it here.
              if os.path.exists(src) and not os.path.exists(dst):
                # Copy the class file.
                safe_mkdir(os.path.dirname(dst))
                os.link(src, dst)

          # Rebase a copy of the per-target analysis files to reflect the merged classes dir.
          if os.path.exists(src_analysis_file):
            src_analysis_file_tmp = \
            os.path.join(tmpdir, os.path.relpath(src_analysis_file, self._analysis_files_base))
            shutil.copyfile(src_analysis_file, src_analysis_file_tmp)
            src_analysis_files.append(src_analysis_file_tmp)
            if self._zinc_utils.run_zinc_rebase(src_analysis_file_tmp, [(src_classes_dir, dst_classes_dir)]):
              self.context.log.warn('In merge_artifact: zinc failed to rebase analysis file %s. '\
                                    'Target may require a full rebuild.' %\
                                    src_analysis_file_tmp)

      dst_deps.save(dst_depfile)

      if self._zinc_utils.run_zinc_merge(src_analysis_files, dst_analysis_file):
        self.context.log.warn('zinc failed to merge analysis files %s to %s. '\
                              'Target may require a full rebuild.' %\
                             (':'.join(src_analysis_files), dst_analysis_file))

  def _split_artifact(self, deps, versioned_target_set):
    """Splits an artifact representing several targets into target-by-target artifacts.
    Creates an output classes dir, a depfile and an analysis file for each target.
    Note that it's not OK to create incomplete artifacts here: this is run *after* a zinc invocation,
    and the expectation is that the result is complete.

    NOTE: This method is reentrant.
    """
    if len(versioned_target_set.targets) <= 1:
      return
    classes_by_source_by_target = deps.findclasses(versioned_target_set.targets)
    src_classes_dir, _, src_analysis_file = self._output_paths(versioned_target_set.targets)

    # Specifies that the list of sources defines a split to the classes dir and analysis file.
    SplitInfo = namedtuple('SplitInfo', ['sources', 'dst_classes_dir', 'dst_analysis_file'])

    analysis_splits = []  # List of SplitInfos.
    portable_analysis_splits = []  # The same, for the portable version of the analysis cache.

    # Prepare the split arguments.
    for target in versioned_target_set.targets:
      classes_by_source = classes_by_source_by_target.get(target, {})
      dst_classes_dir, dst_depfile, dst_analysis_file = self._output_paths([target])
      safe_rmtree(dst_classes_dir)
      safe_mkdir(dst_classes_dir)

      sources = []
      dst_deps = Dependencies(dst_classes_dir)

      for source, classes in classes_by_source.items():
        src = os.path.join(target.target_base, source)
        dst_deps.add(src, classes)
        sources.append(os.path.join(target.target_base, source))
        for cls in classes:
          # Copy the class file.
          dst = os.path.join(dst_classes_dir, cls)
          safe_mkdir(os.path.dirname(dst))
          os.link(os.path.join(src_classes_dir, cls), dst)
      dst_deps.save(dst_depfile)
      analysis_splits.append(SplitInfo(sources, dst_classes_dir, dst_analysis_file))
      portable_analysis_splits.append(SplitInfo(sources, dst_classes_dir, _portable(dst_analysis_file)))

    def do_split(src_analysis_file, splits):
      if os.path.exists(src_analysis_file):
        if self._zinc_utils.run_zinc_split(src_analysis_file, [(x.sources, x.dst_analysis_file) for x in splits]):
          raise TaskError, 'zinc failed to split analysis files %s from %s' %\
                           (':'.join([x.dst_analysis_file for x in splits]), src_analysis_file)
        for split in splits:
          if os.path.exists(split.dst_analysis_file):
            if self._zinc_utils.run_zinc_rebase(split.dst_analysis_file,
                                                [(src_classes_dir, split.dst_classes_dir)]):
              raise TaskError, \
                'In split_artifact: zinc failed to rebase analysis file %s' % split.dst_analysis_file

    # Now rebase the newly created analysis file(s) to reflect the split classes dirs.
    do_split(src_analysis_file, analysis_splits)
    do_split(_portable(src_analysis_file), portable_analysis_splits)

  @staticmethod
  def _calculate_sources(targets):
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
