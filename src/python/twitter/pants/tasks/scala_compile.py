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
# ===================================================================================================

__author__ = 'Benjy Weinberger'

import os

from twitter.pants import has_sources, is_scalac_plugin
from twitter.pants.goal.workunit import WorkUnit
from twitter.pants.targets.scala_library import ScalaLibrary
from twitter.pants.tasks import Task, TaskError
from twitter.pants.tasks.jvm_dependency_cache import JvmDependencyCache
from twitter.pants.tasks.nailgun_task import NailgunTask
from twitter.pants.reporting.reporting_utils import items_to_report_element
from twitter.pants.tasks.scala.zinc_artifact import ZincArtifactFactory, AnalysisFileSpec
from twitter.pants.tasks.scala.zinc_utils import ZincUtils


def _is_scala(target):
  return has_sources(target, '.scala')


class ScalaCompile(NailgunTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('warnings'), mkflag('warnings', negate=True),
                            dest='scala_compile_warnings', default=True,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Compile scala code with all configured warnings '
                                 'enabled.')

    option_group.add_option(mkflag('plugins'), dest='plugins', default=None,
      action='append', help='Use these scalac plugins. Default is set in pants.ini.')

    option_group.add_option(mkflag('partition-size-hint'), dest='scala_compile_partition_size_hint',
      action='store', type='int', default=-1,
      help='Roughly how many source files to attempt to compile together. Set to a large number ' \
           'to compile all sources together. Set this to 0 to compile target-by-target. ' \
           'Default is set in pants.ini.')

    JvmDependencyCache.setup_parser(option_group, args, mkflag)


  def __init__(self, context):
    NailgunTask.__init__(self, context, workdir=context.config.get('scala-compile', 'nailgun_dir'))

    # Set up the zinc utils.
    color = not context.options.no_color
    self._zinc_utils = ZincUtils(context=context, nailgun_task=self, color=color)

    # The rough number of source files to build in each compiler pass.
    self._partition_size_hint = (context.options.scala_compile_partition_size_hint
                                 if context.options.scala_compile_partition_size_hint != -1
                                 else context.config.getint('scala-compile', 'partition_size_hint',
                                                            default=1000))

    # Set up dep checking if needed.
    if context.options.scala_check_missing_deps:
      JvmDependencyCache.init_product_requirements(self)

    self._opts = context.config.getlist('scala-compile', 'args')
    if context.options.scala_compile_warnings:
      self._opts.extend(context.config.getlist('scala-compile', 'warning_args'))
    else:
      self._opts.extend(context.config.getlist('scala-compile', 'no_warning_args'))

    # Various output directories.
    workdir = context.config.get('scala-compile', 'workdir')
    self._resources_dir = os.path.join(workdir, 'resources')
    self._artifact_factory = ZincArtifactFactory(workdir, self.context, self._zinc_utils)

    # The ivy confs for which we're building.
    self._confs = context.config.getlist('scala-compile', 'confs')

    # The artifact cache to read from/write to.
    artifact_cache_spec = context.config.getlist('scala-compile', 'artifact_caches', default=[])
    self.setup_artifact_cache(artifact_cache_spec)

    # If we are compiling scala libraries with circular deps on java libraries we need to make sure
    # those cycle deps are present.
    self._inject_java_cycles()

  def _inject_java_cycles(self):
    for scala_target in self.context.targets(lambda t: isinstance(t, ScalaLibrary)):
      for java_target in scala_target.java_sources:
        self.context.add_target(java_target)

  def product_type(self):
    return 'classes'

  def can_dry_run(self):
    return True

  def execute(self, targets):
    scala_targets = filter(_is_scala, targets)
    if not scala_targets:
      return

    # Get the classpath generated by upstream JVM tasks (including previous calls to execute()).
    with self.context.state('classpath', []) as cp:
      self._add_globally_required_classpath_entries(cp)
      with self.context.state('upstream_analysis_map', {}) as upstream_analysis_map:
        with self.invalidated(scala_targets, invalidate_dependents=True,
                              partition_size_hint=self._partition_size_hint) as invalidation_check:
          # Process partitions one by one.
          for vts in invalidation_check.all_vts_partitioned:
            if not self.dry_run:
              merged_artifact = self._process_target_partition(vts, cp, upstream_analysis_map)
              vts.update()
              # Note that we add the merged classes_dir to the upstream.
              # This is because zinc doesn't handle many upstream dirs well.
              if os.path.exists(merged_artifact.classes_dir):
                for conf in self._confs:
                  cp.append((conf, merged_artifact.classes_dir))
                if os.path.exists(merged_artifact.analysis_file):
                  upstream_analysis_map[merged_artifact.classes_dir] = \
                    AnalysisFileSpec(merged_artifact.analysis_file, merged_artifact.classes_dir)

    # Check for missing dependencies.
    all_analysis_files = set()
    for target in scala_targets:
      analysis_file_spec = self._artifact_factory.analysis_file_for_targets([target])
      if os.path.exists(analysis_file_spec.analysis_file):
        all_analysis_files.add(analysis_file_spec)
    deps_cache = JvmDependencyCache(self.context, scala_targets, all_analysis_files)
    deps_cache.check_undeclared_dependencies()

  def _add_globally_required_classpath_entries(self, cp):
    # Add classpath entries necessary both for our compiler calls and for downstream JVM tasks.
    for conf in self._confs:
      cp.insert(0, (conf, self._resources_dir))
      for jar in self._zinc_utils.plugin_jars():
        cp.insert(0, (conf, jar))

  def _localize_portable_analysis_files(self, vts):
    # Localize the analysis files we read from the artifact cache.
    for vt in vts:
      analysis_file = self._artifact_factory.analysis_file_for_targets(vt.targets)
      if self._zinc_utils.localize_analysis_file(
          ZincArtifactFactory.portable(analysis_file.analysis_file), analysis_file.analysis_file):
        self.context.log.warn('Zinc failed to localize analysis file: %s. Incremental rebuild' \
                              'of that target may not be possible.' % analysis_file)

  def check_artifact_cache(self, vts):
    # Special handling for scala artifacts.
    cached_vts, uncached_vts = Task.check_artifact_cache(self, vts)

    if cached_vts:
      # Localize the portable analysis files.
      with self.context.new_workunit('localize', labels=[WorkUnit.MULTITOOL]):
        self._localize_portable_analysis_files(cached_vts)

      # Split any merged artifacts.
      for vt in cached_vts:
        if len(vt.targets) > 1:
          artifacts = [self._artifact_factory.artifact_for_target(t) for t in vt.targets]
          merged_artifact = self._artifact_factory.merged_artifact(artifacts)
          merged_artifact.split()
          for v in vt.versioned_targets:
            v.update()
    return cached_vts, uncached_vts

  def _process_target_partition(self, vts, cp, upstream_analysis_map):
    """Must run on all target partitions, not just invalid ones.

    May be invoked concurrently on independent target sets.

    Postcondition: The individual targets in vts are up-to-date, as if each were
                   compiled individually.
    """
    artifacts = [self._artifact_factory.artifact_for_target(target) for target in vts.targets]
    merged_artifact = self._artifact_factory.merged_artifact(artifacts)

    if not merged_artifact.sources:
      self.context.log.warn('Skipping scala compile for targets with no sources:\n  %s' %
                            merged_artifact.targets)
    else:
      # Get anything we have from previous builds (or we pulled from the artifact cache).
      # We must do this even if we're not going to compile, because the merged output dir
      # will go on the classpath of downstream tasks. We can't put the per-target dirs
      # on the classpath because Zinc doesn't handle large numbers of upstream deps well.
      current_state = merged_artifact.merge(force=not vts.valid)

      # Note: vts.valid tells us if the merged artifact is valid. If not, we recreate it
      # above. [not vt.valid for vt in vts.versioned_targets] tells us if anything needs
      # to be recompiled. The distinction is important: all the underlying targets may be
      # valid because they were built in some other pants run with different partitions,
      # but this partition may still be invalid and need merging.

      # Invoke the compiler if needed.
      if any([not vt.valid for vt in vts.versioned_targets]):
        # Do some reporting.
        self.context.log.info(
          'Operating on a partition containing ',
          items_to_report_element(vts.cache_key.sources, 'source'),
          ' in ',
          items_to_report_element([t.address.reference() for t in vts.targets], 'target'), '.')
        old_state = current_state
        classpath = [entry for conf, entry in cp if conf in self._confs]
        with self.context.new_workunit('compile'):
          # Zinc may delete classfiles, then later exit on a compilation error. Then if the
          # change triggering the error is reverted, we won't rebuild to restore the missing
          # classfiles. So we force-invalidate here, to be on the safe side.
          vts.force_invalidate()
          if self._zinc_utils.compile(classpath, merged_artifact.sources,
                                      merged_artifact.classes_dir,
                                      merged_artifact.analysis_file, upstream_analysis_map):
            raise TaskError('Compile failed.')

        write_to_artifact_cache = self._artifact_cache and \
                                  self.context.options.write_to_artifact_cache
        current_state = merged_artifact.split(old_state, portable=write_to_artifact_cache)

        if write_to_artifact_cache:
          # Write the entire merged artifact, and each individual split artifact,
          # to the artifact cache, if needed.
          vts_artifact_pairs = zip(vts.versioned_targets, artifacts) + [(vts, merged_artifact)]
          self._update_artifact_cache(vts_artifact_pairs)

      # Register the products, if needed. TODO: Make sure this is safe to call concurrently.
      # In practice the GIL will make it fine, but relying on that is insanitary.
      if self.context.products.isrequired('classes'):
        self._add_products_to_genmap(merged_artifact, current_state)
    return merged_artifact

  def _add_products_to_genmap(self, artifact, state):
    """Must be called on all targets, whether they needed compilation or not."""
    genmap = self.context.products.get('classes')
    for target, sources in artifact.sources_by_target.items():
      for source in sources:
        classes = state.classes_by_src.get(source, [])
        relsrc = os.path.relpath(source, target.target_base)
        genmap.add(relsrc, artifact.classes_dir, classes)
        genmap.add(target, artifact.classes_dir, classes)
      # TODO(John Sirois): Map target.resources in the same way
      # Create and Map scala plugin info files to the owning targets.
      if is_scalac_plugin(target) and target.classname:
        basedir, plugin_info_file = self._zinc_utils.write_plugin_info(self._resources_dir, target)
        genmap.add(target, basedir, [plugin_info_file])

  def _update_artifact_cache(self, vts_artifact_pairs):
    # Relativize the analysis.
    # TODO: Relativize before splitting? This will require changes to Zinc, which currently
    # eliminates paths it doesn't recognize (including our placeholders) when splitting.
    vts_artifactfiles_pairs = []
    with self.context.new_workunit(name='cacheprep'):
      with self.context.new_workunit(name='relativize', labels=[WorkUnit.MULTITOOL]):
        for vts, artifact in vts_artifact_pairs:
          if os.path.exists(artifact.analysis_file) and \
              self._zinc_utils.relativize_analysis_file(artifact.analysis_file,
                                                        artifact.portable_analysis_file):
            raise TaskError('Zinc failed to relativize analysis file: %s' % artifact.analysis_file)
          artifact_files = [artifact.classes_dir, artifact.portable_analysis_file]
          vts_artifactfiles_pairs.append((vts, artifact_files))

    self.update_artifact_cache(vts_artifactfiles_pairs)
