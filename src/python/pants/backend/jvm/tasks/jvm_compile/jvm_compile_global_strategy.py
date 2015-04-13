# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os
import shutil
import uuid
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.backend.jvm.tasks.jvm_compile.jvm_compile_strategy import JvmCompileStrategy
from pants.backend.jvm.tasks.jvm_compile.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.backend.jvm.tasks.jvm_compile.resource_mapping import ResourceMapping
from pants.base.build_environment import get_buildroot, get_scm
from pants.base.exceptions import TaskError
from pants.base.target import Target
from pants.base.worker_pool import Work
from pants.option.options import Options
from pants.util.contextutil import open_zip, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_rmtree, safe_walk


class JvmCompileGlobalStrategy(JvmCompileStrategy):
  """A strategy for JVM compilation that uses a global classpath and analysis."""

  @classmethod
  def register_options(cls, register, language):
    register('--missing-deps', choices=['off', 'warn', 'fatal'], default='warn',
             help='Check for missing dependencies in {0} code. Reports actual dependencies A -> B '
                  'where there is no transitive BUILD file dependency path from A to B. If fatal, '
                  'missing deps are treated as a build error.'.format(language))

    register('--missing-direct-deps', choices=['off', 'warn', 'fatal'], default='off',
             help='Check for missing direct dependencies in {0} code. Reports actual dependencies '
                  'A -> B where there is no direct BUILD file dependency path from A to B. This is '
                  'a very strict check; In practice it is common to rely on transitive, indirect '
                  'dependencies, e.g., due to type inference or when the main target in a BUILD '
                  'file is modified to depend on other targets in the same BUILD file, as an '
                  'implementation detail. However it may still be useful to use this on '
                  'occasion. '.format(language))

    register('--missing-deps-whitelist', type=Options.list,
             help="Don't report these targets even if they have missing deps.")

    register('--unnecessary-deps', choices=['off', 'warn', 'fatal'], default='off',
             help='Check for declared dependencies in {0} code that are not needed. This is a very '
                  'strict check. For example, generated code will often legitimately have BUILD '
                  'dependencies that are unused in practice.'.format(language))

    register('--changed-targets-heuristic-limit', type=int, default=0,
             help='If non-zero, and we have fewer than this number of locally-changed targets, '
                  'partition them separately, to preserve stability when compiling repeatedly.')

    register('--delete-scratch', default=True, action='store_true',
             help='Leave intermediate scratch files around, for debugging build problems.')

  def __init__(self, context, options, workdir, analysis_tools, sources_predicate):
    super(JvmCompileGlobalStrategy, self).__init__(context, options, workdir, analysis_tools, sources_predicate)

    # Various working directories.
    # NB: These are grandfathered in with non-strategy-specific names, but to prevent
    # collisions within the buildcache, strategies should use strategy-specific subdirectories.
    self._analysis_dir = os.path.join(workdir, 'analysis')
    self._classes_dir = os.path.join(workdir, 'classes')

    self._delete_scratch = options.delete_scratch

    self._analysis_file = os.path.join(self._analysis_dir, 'global_analysis.valid')
    self._invalid_analysis_file = os.path.join(self._analysis_dir, 'global_analysis.invalid')

    self._target_sources_dir = os.path.join(workdir, 'target_sources')

    # A temporary, but well-known, dir in which to munge analysis/dependency files in before
    # caching. It must be well-known so we know where to find the files when we retrieve them from
    # the cache.
    self._analysis_tmpdir = os.path.join(self._analysis_dir, 'artifact_cache_tmpdir')

    # The rough number of source files to build in each compiler pass.
    self._partition_size_hint = options.partition_size_hint

    # Set up dep checking if needed.
    def munge_flag(flag):
      flag_value = getattr(options, flag, None)
      return None if flag_value == 'off' else flag_value

    check_missing_deps = munge_flag('missing_deps')
    check_missing_direct_deps = munge_flag('missing_direct_deps')
    check_unnecessary_deps = munge_flag('unnecessary_deps')

    if check_missing_deps or check_missing_direct_deps or check_unnecessary_deps:
      target_whitelist = options.missing_deps_whitelist
      # Must init it here, so it can set requirements on the context.
      self._dep_analyzer = JvmDependencyAnalyzer(self.context,
                                                 check_missing_deps,
                                                 check_missing_direct_deps,
                                                 check_unnecessary_deps,
                                                 target_whitelist)
    else:
      self._dep_analyzer = None

    # Computed lazily as needed.
    self._upstream_class_to_path = None

    # If non-zero, and we have fewer than this number of locally-changed targets,
    # then we partition them separately, to preserve stability in the face of repeated
    # compilations.
    self._changed_targets_heuristic_limit = options.changed_targets_heuristic_limit

    # Sources (relative to buildroot) present in the last analysis that have since been deleted.
    # Populated in prepare_compile().
    self._deleted_sources = None

  def name(self):
    return 'global'

  def compile_context(self, target):
    """Returns the default/stable compile context for the given target.

    Temporary compile contexts are private to the strategy.
    """
    return self.CompileContext(target,
                               self._analysis_file,
                               self._classes_dir,
                               self._sources_for_target(target))

  def move(self, src, dst):
    if self._delete_scratch:
      shutil.move(src, dst)
    else:
      shutil.copy(src, dst)

  def pre_compile(self):
    # Only create these working dirs during execution phase, otherwise, they
    # would be wiped out by clean-all goal/task if it's specified.
    safe_mkdir(self._target_sources_dir)
    safe_mkdir(self._analysis_dir)
    safe_mkdir(self._classes_dir)

    # Look for invalid analysis files.
    for f in (self._invalid_analysis_file, self._analysis_file):
      self.validate_analysis(f)

  def prepare_compile(self, cache_manager, all_targets, relevant_targets):
    super(JvmCompileGlobalStrategy, self).prepare_compile(cache_manager, all_targets, relevant_targets)

    # Update the classpath for us and for downstream tasks.
    compile_classpaths = self.context.products.get_data('compile_classpath')
    for conf in self._confs:
      compile_classpaths.add_for_targets(all_targets, [(conf, self._classes_dir)])

    # Split the global analysis file into valid and invalid parts.
    invalidation_check = cache_manager.check(relevant_targets)
    if invalidation_check.invalid_vts:
      # The analysis for invalid and deleted sources is no longer valid.
      invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]
      invalid_sources_by_target = {}
      for tgt in invalid_targets:
        invalid_sources_by_target[tgt] = self._sources_for_target(tgt)
      invalid_sources = list(itertools.chain.from_iterable(invalid_sources_by_target.values()))
      self._deleted_sources = self._compute_deleted_sources()

      self._ensure_analysis_tmpdir()
      tmpdir = os.path.join(self._analysis_tmpdir, str(uuid.uuid4()))
      os.mkdir(tmpdir)
      valid_analysis_tmp = os.path.join(tmpdir, 'valid_analysis')
      newly_invalid_analysis_tmp = os.path.join(tmpdir, 'newly_invalid_analysis')
      invalid_analysis_tmp = os.path.join(tmpdir, 'invalid_analysis')
      if self._analysis_parser.is_nonempty_analysis(self._analysis_file):
        with self.context.new_workunit(name='prepare-analysis'):
          self._analysis_tools.split_to_paths(self._analysis_file,
              [(invalid_sources + self._deleted_sources, newly_invalid_analysis_tmp)],
              valid_analysis_tmp)
          if self._analysis_parser.is_nonempty_analysis(self._invalid_analysis_file):
            self._analysis_tools.merge_from_paths(
              [self._invalid_analysis_file, newly_invalid_analysis_tmp], invalid_analysis_tmp)
          else:
            invalid_analysis_tmp = newly_invalid_analysis_tmp

          # Now it's OK to overwrite the main analysis files with the new state.
          self.move(valid_analysis_tmp, self._analysis_file)
          self.move(invalid_analysis_tmp, self._invalid_analysis_file)
    else:
      self._deleted_sources = []

  def invalidation_hints(self, relevant_targets):
    # If needed, find targets that we've changed locally (as opposed to
    # changes synced in from the SCM).
    # TODO(benjy): Should locally_changed_targets be available in all Tasks?
    locally_changed_targets = None
    if self._changed_targets_heuristic_limit:
      locally_changed_targets = self._find_locally_changed_targets(relevant_targets)
      if (locally_changed_targets and
          len(locally_changed_targets) > self._changed_targets_heuristic_limit):
        locally_changed_targets = None

    return (self._partition_size_hint, locally_changed_targets)

  def compile_chunk(self,
                    invalidation_check,
                    all_targets,
                    relevant_targets,
                    invalid_targets,
                    extra_compile_time_classpath_elements,
                    compile_vts,
                    register_vts,
                    update_artifact_cache_vts_work):
    """Executes compilations for the invalid targets contained in a single chunk.

    Has the side effects of populating:
    # valid/invalid analysis files
    # classes_by_source product
    # classes_by_target product
    # resources_by_target product
    """
    assert invalid_targets, "compile_chunk should only be invoked if there are invalid targets."

    # Get the classpath generated by upstream JVM tasks and our own prepare_compile().
    compile_classpaths = self.context.products.get_data('compile_classpath')

    # Add any extra compile-time-only classpath elements.
    # TODO(benjy): Model compile-time vs. runtime classpaths more explicitly.
    # TODO(benjy): Add a pre-execute goal for injecting deps into targets, so e.g.,
    # we can inject a dep on the scala runtime library and still have it ivy-resolve.
    def extra_compile_classpath_iter():
      for conf in self._confs:
        for jar in extra_compile_time_classpath_elements:
          yield (conf, jar)
    # NB: The global strategy uses the aggregated classpath (for all targets) to compile each
    # chunk, which avoids needing to introduce compile-time dependencies between annotation
    # processors and the classes they annotate.
    compile_classpath = compile_classpaths.get_for_targets(all_targets)
    compile_classpath = OrderedSet(list(extra_compile_classpath_iter()) + list(compile_classpath))

    # Validate that all classpath entries are located within the working copy, which
    # simplifies relativizing the analysis files.
    self._validate_classpath(compile_classpath)

    # Find the invalid sources for this chunk.
    invalid_sources_by_target = {t: self._sources_for_target(t) for t in invalid_targets}

    tmpdir = os.path.join(self._analysis_tmpdir, str(uuid.uuid4()))
    os.mkdir(tmpdir)

    # Figure out the sources and analysis belonging to each partition.
    partitions = []  # Each element is a triple (vts, sources_by_target, analysis).
    for vts in invalidation_check.invalid_vts_partitioned:
      partition_tmpdir = os.path.join(tmpdir, Target.maybe_readable_identify(vts.targets))
      os.mkdir(partition_tmpdir)
      sources = list(itertools.chain.from_iterable(
          [invalid_sources_by_target.get(t, []) for t in vts.targets]))
      de_duped_sources = list(OrderedSet(sources))
      if len(sources) != len(de_duped_sources):
        counts = [(src, len(list(srcs))) for src, srcs in itertools.groupby(sorted(sources))]
        self.context.log.warn(
            'De-duped the following sources:\n\t{}'
            .format('\n\t'.join(sorted('{} {}'.format(cnt, src) for src, cnt in counts if cnt > 1))))
      analysis_file = os.path.join(partition_tmpdir, 'analysis')
      partitions.append((vts, de_duped_sources, analysis_file))

    # Split per-partition files out of the global invalid analysis.
    if self._analysis_parser.is_nonempty_analysis(self._invalid_analysis_file) and partitions:
      with self.context.new_workunit(name='partition-analysis'):
        splits = [(x[1], x[2]) for x in partitions]
        # We have to pass the analysis for any deleted files through zinc, to give it
        # a chance to delete the relevant class files.
        if splits:
          splits[0] = (splits[0][0] + self._deleted_sources, splits[0][1])
        self._analysis_tools.split_to_paths(self._invalid_analysis_file, splits)

    # Now compile partitions one by one.
    for partition_index, partition in enumerate(partitions):
      (vts, sources, analysis_file) = partition
      cp_entries = [entry for conf, entry in compile_classpath if conf in self._confs]

      progress_message = 'partition {} of {}'.format(partition_index + 1, len(partitions))
      # We have to treat the global output dir as an upstream element, so compilers can
      # find valid analysis for previous partitions. We use the global valid analysis
      # for the upstream.
      upstream_analysis = ({self._classes_dir: self._analysis_file}
                           if os.path.exists(self._analysis_file) else {})
      compile_vts(vts,
                  sources,
                  analysis_file,
                  upstream_analysis,
                  cp_entries,
                  self._classes_dir,
                  progress_message)

      # No exception was thrown, therefore the compile succeeded and analysis_file is now valid.
      if os.path.exists(analysis_file):  # The compilation created an analysis.
        # Merge the newly-valid analysis with our global valid analysis.
        new_valid_analysis = analysis_file + '.valid.new'
        if self._analysis_parser.is_nonempty_analysis(self._analysis_file):
          with self.context.new_workunit(name='update-upstream-analysis'):
            self._analysis_tools.merge_from_paths([self._analysis_file, analysis_file],
                                                  new_valid_analysis)
        else:  # We need to keep analysis_file around. Background tasks may need it.
          shutil.copy(analysis_file, new_valid_analysis)

        # Move the merged valid analysis to its proper location.
        # We do this before checking for missing dependencies, so that we can still
        # enjoy an incremental compile after fixing missing deps.
        self.move(new_valid_analysis, self._analysis_file)

        # Update the products with the latest classes. Must happen before the
        # missing dependencies check.
        register_vts([self.compile_context(t) for t in vts.targets])
        if self._dep_analyzer:
          # Check for missing dependencies.
          actual_deps = self._analysis_parser.parse_deps_from_path(analysis_file,
              lambda: self._compute_classpath_elements_by_class(cp_entries), self._classes_dir)
          with self.context.new_workunit(name='find-missing-dependencies'):
            self._dep_analyzer.check(sources, actual_deps)

        # Kick off the background artifact cache write.
        if update_artifact_cache_vts_work:
          self._write_to_artifact_cache(analysis_file,
                                        vts,
                                        update_artifact_cache_vts_work)

      if self._analysis_parser.is_nonempty_analysis(self._invalid_analysis_file):
        with self.context.new_workunit(name='trim-downstream-analysis'):
          # Trim out the newly-valid sources from our global invalid analysis.
          new_invalid_analysis = analysis_file + '.invalid.new'
          discarded_invalid_analysis = analysis_file + '.invalid.discard'
          self._analysis_tools.split_to_paths(self._invalid_analysis_file,
            [(sources, discarded_invalid_analysis)], new_invalid_analysis)
          self.move(new_invalid_analysis, self._invalid_analysis_file)

      # Record the built target -> sources mapping for future use.
      for target, sources in self._sources_for_targets(vts.targets).items():
        self._record_previous_sources_by_target(target, sources)

      # Now that all the analysis accounting is complete, and we have no missing deps,
      # we can safely mark the targets as valid.
      vts.update()

  def compute_resource_mapping(self, compile_contexts):
    return ResourceMapping(self._classes_dir)

  def compute_classes_by_source(self, compile_contexts):
    if not compile_contexts:
      return {}

    # This implementation requires that all contexts use the same analysis file and global classes.
    analysis_file = None
    for compile_context in compile_contexts:
      if compile_context.classes_dir != self._classes_dir:
        raise TaskError('Unrecognized classes directory for the global strategy: {}'.format(
          compile_context.classes_dir))
      if not analysis_file:
        analysis_file = compile_context.analysis_file
      else:
        if compile_context.analysis_file != analysis_file:
          raise TaskError('Inconsistent analysis file for the global strategy: {} vs {}'.format(
            compile_context.analysis_file, analysis_file))

    classes_by_src_by_context = defaultdict(dict)
    if os.path.exists(analysis_file):
      # Parse the global analysis once.
      buildroot = get_buildroot()
      products = self._analysis_parser.parse_products_from_path(analysis_file,
                                                                self._classes_dir)

      # Then iterate over contexts (targets), and add the classes for their sources.
      for compile_context in compile_contexts:
        classes_by_src = classes_by_src_by_context[compile_context]
        for source in compile_context.sources:
          absolute_source = os.path.join(buildroot, source)
          classes_by_src[source] = products.get(absolute_source, [])
    return classes_by_src_by_context

  def post_process_cached_vts(self, cached_vts):
    """Special post processing for global scala analysis files.

    Class files are retrieved directly into their final locations in the global classes dir.
    """
    self._ensure_analysis_tmpdir()

    # Get all the targets whose artifacts we found in the cache.
    cached_targets = []
    for vt in cached_vts:
      for target in vt.targets:
        cached_targets.append(target)

    # The current global analysis may contain old data for modified targets for
    # which we got cache hits. We need to strip out this old analysis, to ensure
    # that the new data incoming from the cache doesn't collide with it during the merge.
    sources_to_strip = []
    if os.path.exists(self._analysis_file):
      for target in cached_targets:
        sources_to_strip.extend(self._get_previous_sources_by_target(target))

    # Localize the cached analyses.
    analyses_to_merge = []
    for target in cached_targets:
      analysis_file = JvmCompileStrategy._analysis_for_target(self._analysis_tmpdir, target)
      portable_analysis_file = JvmCompileStrategy._portable_analysis_for_target(self._analysis_tmpdir,
                                                                        target)
      if os.path.exists(portable_analysis_file):
        self._analysis_tools.localize(portable_analysis_file, analysis_file)
      if os.path.exists(analysis_file):
        analyses_to_merge.append(analysis_file)

    # Merge them into the global analysis.
    if analyses_to_merge:
      with temporary_dir() as tmpdir:
        if sources_to_strip:
          throwaway = os.path.join(tmpdir, 'throwaway')
          trimmed_analysis = os.path.join(tmpdir, 'trimmed')
          self._analysis_tools.split_to_paths(self._analysis_file,
                                          [(sources_to_strip, throwaway)],
                                          trimmed_analysis)
        else:
          trimmed_analysis = self._analysis_file
        if os.path.exists(trimmed_analysis):
          analyses_to_merge.append(trimmed_analysis)
        tmp_analysis = os.path.join(tmpdir, 'analysis')
        with self.context.new_workunit(name='merge_analysis'):
          self._analysis_tools.merge_from_paths(analyses_to_merge, tmp_analysis)

        sources_by_cached_target = self._sources_for_targets(cached_targets)

        # Record the cached target -> sources mapping for future use.
        for target, sources in sources_by_cached_target.items():
          self._record_previous_sources_by_target(target, sources)

        # Everything's good so move the merged analysis to its final location.
        if os.path.exists(tmp_analysis):
          self.move(tmp_analysis, self._analysis_file)

  def _write_to_artifact_cache(self, analysis_file, vts, get_update_artifact_cache_work):
    vt_by_target = dict([(vt.target, vt) for vt in vts.versioned_targets])

    vts_targets = [t for t in vts.targets if not t.has_label('no_cache')]

    # Determine locations for analysis files that will be split in the background.
    split_analysis_files = [
        JvmCompileStrategy._analysis_for_target(self._analysis_tmpdir, t) for t in vts_targets]
    portable_split_analysis_files = [
        JvmCompileStrategy._portable_analysis_for_target(self._analysis_tmpdir, t) for t in vts_targets]

    # Set up args for splitting the analysis into per-target files.
    splits = zip([self._sources_for_target(t) for t in vts_targets], split_analysis_files)
    splits_args_tuples = [(analysis_file, splits)]

    # Set up args for rebasing the splits.
    relativize_args_tuples = zip(split_analysis_files, portable_split_analysis_files)

    # Compute the classes and resources for each vts.
    compile_contexts = [self.compile_context(t) for t in vts_targets]
    vts_artifactfiles_pairs = []
    classes_by_source_by_context = self.compute_classes_by_source(compile_contexts)
    resources_by_target = self.context.products.get_data('resources_by_target')
    for compile_context in compile_contexts:
      target = compile_context.target
      if target.has_label('no_cache'):
        continue
      artifacts = []
      if resources_by_target is not None:
        for _, paths in resources_by_target[target].abs_paths():
          artifacts.extend(paths)
      classes_by_source = classes_by_source_by_context[compile_context]
      for source in compile_context.sources:
        classes = classes_by_source.get(source, [])
        artifacts.extend(classes)

      vt = vt_by_target.get(target)
      if vt is not None:
        # NOTE: analysis_file doesn't exist yet.
        vts_artifactfiles_pairs.append(
            (vt,
             artifacts + [JvmCompileStrategy._portable_analysis_for_target(self._analysis_tmpdir, target)]))

    update_artifact_cache_work = get_update_artifact_cache_work(vts_artifactfiles_pairs)
    if update_artifact_cache_work:
      work_chain = [
        Work(self._analysis_tools.split_to_paths, splits_args_tuples, 'split'),
        Work(self._analysis_tools.relativize, relativize_args_tuples, 'relativize'),
        update_artifact_cache_work
      ]
      self.context.submit_background_work_chain(work_chain, parent_workunit_name='cache')

  def _get_previous_sources_by_target(self, target):
    """Returns the target's sources as recorded on the last successful build of target.

    Returns a list of absolute paths.
    """
    path = os.path.join(self._target_sources_dir, target.identifier)
    if os.path.exists(path):
      with open(path, 'r') as infile:
        return [s.rstrip() for s in infile.readlines()]
    else:
      return []

  def _record_previous_sources_by_target(self, target, sources):
    # Record target -> source mapping for future use.
    with open(os.path.join(self._target_sources_dir, target.identifier), 'w') as outfile:
      for src in sources:
        outfile.write(os.path.join(get_buildroot(), src))
        outfile.write('\n')

  def _compute_deleted_sources(self):
    """Computes the list of sources present in the last analysis that have since been deleted.

    This is a global list. We have no way of associating them to individual targets.
    Paths are relative to buildroot.
    """
    with self.context.new_workunit('find-deleted-sources'):
      if os.path.exists(self._analysis_file):
        products = self._analysis_parser.parse_products_from_path(self._analysis_file,
                                                                  self._classes_dir)
        buildroot = get_buildroot()
        old_srcs = products.keys()  # Absolute paths.
        return [os.path.relpath(src, buildroot) for src in old_srcs if not os.path.exists(src)]
      else:
        return []

  def _find_locally_changed_targets(self, relevant_targets):
    """Finds the targets whose sources have been modified locally.

    Returns a list of targets, or None if no SCM is available.
    """
    # Compute the src->targets mapping. There should only be one target per source,
    # but that's not yet a hard requirement, so the value is a list of targets.
    # TODO(benjy): Might this inverse mapping be needed elsewhere too?
    targets_by_source = defaultdict(list)
    for tgt, srcs in self._sources_for_targets(relevant_targets).items():
      for src in srcs:
        targets_by_source[src].append(tgt)

    ret = OrderedSet()
    scm = get_scm()
    if not scm:
      return None
    changed_files = scm.changed_files(include_untracked=True, relative_to=get_buildroot())
    for f in changed_files:
      ret.update(targets_by_source.get(f, []))
    return list(ret)

  def _compute_classpath_elements_by_class(self, classpath):
    # Don't consider loose classes dirs in our classes dir. Those will be considered
    # separately, by looking at products.
    def non_product(path):
      return path != self._classes_dir

    if self._upstream_class_to_path is None:
      self._upstream_class_to_path = {}
      classpath_entries = filter(non_product, classpath)
      for cp_entry in self._find_all_bootstrap_jars() + classpath_entries:
        # Per the classloading spec, a 'jar' in this context can also be a .zip file.
        if os.path.isfile(cp_entry) and ((cp_entry.endswith('.jar') or cp_entry.endswith('.zip'))):
          with open_zip(cp_entry, 'r') as jar:
            for cls in jar.namelist():
              # First jar with a given class wins, just like when classloading.
              if cls.endswith(b'.class') and not cls in self._upstream_class_to_path:
                self._upstream_class_to_path[cls] = cp_entry
        elif os.path.isdir(cp_entry):
          for dirpath, _, filenames in safe_walk(cp_entry, followlinks=True):
            for f in filter(lambda x: x.endswith('.class'), filenames):
              cls = os.path.relpath(os.path.join(dirpath, f), cp_entry)
              if not cls in self._upstream_class_to_path:
                self._upstream_class_to_path[cls] = os.path.join(dirpath, f)
    return self._upstream_class_to_path

  def _find_all_bootstrap_jars(self):
    def get_path(key):
      return self.context.java_sysprops.get(key, '').split(':')

    def find_jars_in_dirs(dirs):
      ret = []
      for d in dirs:
        if os.path.isdir(d):
          ret.extend(filter(lambda s: s.endswith('.jar'), os.listdir(d)))
      return ret

    # Note: assumes HotSpot, or some JVM that supports sun.boot.class.path.
    # TODO: Support other JVMs? Not clear if there's a standard way to do so.
    # May include loose classes dirs.
    boot_classpath = get_path('sun.boot.class.path')

    # Note that per the specs, overrides and extensions must be in jars.
    # Loose class files will not be found by the JVM.
    override_jars = find_jars_in_dirs(get_path('java.endorsed.dirs'))
    extension_jars = find_jars_in_dirs(get_path('java.ext.dirs'))

    # Note that this order matters: it reflects the classloading order.
    bootstrap_jars = filter(os.path.isfile, override_jars + boot_classpath + extension_jars)
    return bootstrap_jars  # Technically, may include loose class dirs from boot_classpath.

  # Work in a tmpdir so we don't stomp the main analysis files on error.
  # The tmpdir is cleaned up in a shutdown hook, because background work
  # may need to access files we create there even after this method returns.
  def _ensure_analysis_tmpdir(self):
    # Do this lazily, so we don't trigger creation of a worker pool unless we need it.
    if not os.path.exists(self._analysis_tmpdir):
      os.makedirs(self._analysis_tmpdir)
      if self._delete_scratch:
        self.context.background_worker_pool().add_shutdown_hook(
            lambda: safe_rmtree(self._analysis_tmpdir))
