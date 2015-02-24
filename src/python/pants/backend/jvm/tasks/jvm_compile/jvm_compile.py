# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os
import shutil
import sys
import uuid
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.group_task import GroupMember
from pants.backend.jvm.tasks.jvm_compile.jvm_compile_strategy import JvmCompileStrategy
from pants.backend.jvm.tasks.jvm_compile.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.backend.jvm.tasks.jvm_compile.jvm_fingerprint_strategy import JvmFingerprintStrategy
from pants.backend.jvm.tasks.jvm_compile.resource_mapping import ResourceMapping
from pants.backend.jvm.tasks.nailgun_task import NailgunTaskBase
from pants.base.build_environment import get_buildroot, get_scm
from pants.base.exceptions import TaskError
from pants.base.target import Target
from pants.base.worker_pool import Work
from pants.goal.products import MultipleRootedProducts
from pants.option.options import Options
from pants.reporting.reporting_utils import items_to_report_element
from pants.util.contextutil import open_zip64, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_rmtree, safe_walk


class JvmCompile(NailgunTaskBase, GroupMember):
  """A common framework for JVM compilation.

  To subclass for a specific JVM language, implement the static values and methods
  mentioned below under "Subclasses must implement".
  """

  @classmethod
  def register_options(cls, register):
    super(JvmCompile, cls).register_options(register)
    register('--partition-size-hint', type=int, default=sys.maxint, metavar='<# source files>',
             help='Roughly how many source files to attempt to compile together. Set to a large '
                  'number to compile all sources together. Set to 0 to compile target-by-target.')

    register('--jvm-options', type=Options.list,
             help='Run the compiler with these JVM options.')

    register('--args', action='append', default=list(cls.get_args_default(register.bootstrap)),
             help='Pass these args to the compiler.')

    register('--confs', type=Options.list, default=['default'],
             help='Compile for these Ivy confs.')

    register('--warnings', default=True, action='store_true',
             help='Compile with all configured warnings enabled.')

    register('--warning-args', action='append', default=list(cls.get_warning_args_default()),
             help='Extra compiler args to use when warnings are enabled.')

    register('--no-warning-args', action='append', default=list(cls.get_no_warning_args_default()),
             help='Extra compiler args to use when warnings are disabled.')

    register('--missing-deps', choices=['off', 'warn', 'fatal'], default='warn',
             help='Check for missing dependencies in {0} code. Reports actual dependencies A -> B '
                  'where there is no transitive BUILD file dependency path from A to B. If fatal, '
                  'missing deps are treated as a build error.'.format(cls._language))

    register('--missing-direct-deps', choices=['off', 'warn', 'fatal'], default='off',
             help='Check for missing direct dependencies in {0} code. Reports actual dependencies '
                  'A -> B where there is no direct BUILD file dependency path from A to B. This is '
                  'a very strict check; In practice it is common to rely on transitive, indirect '
                  'dependencies, e.g., due to type inference or when the main target in a BUILD '
                  'file is modified to depend on other targets in the same BUILD file, as an '
                  'implementation detail. However it may still be useful to use this on '
                  'occasion. '.format(cls._language))

    register('--missing-deps-whitelist', type=Options.list,
             help="Don't report these targets even if they have missing deps.")

    register('--unnecessary-deps', choices=['off', 'warn', 'fatal'], default='off',
             help='Check for declared dependencies in {0} code that are not needed. This is a very '
                  'strict check. For example, generated code will often legitimately have BUILD '
                  'dependencies that are unused in practice.'.format(cls._language))

    register('--changed-targets-heuristic-limit', type=int, default=0,
             help='If non-zero, and we have fewer than this number of locally-changed targets, '
                  'partition them separately, to preserve stability when compiling repeatedly.')

    register('--delete-scratch', default=True, action='store_true',
             help='Leave intermediate scratch files around, for debugging build problems.')

  @classmethod
  def product_types(cls):
    return ['classes_by_target', 'classes_by_source', 'resources_by_target']

  @classmethod
  def prepare(cls, options, round_manager):
    super(JvmCompile, cls).prepare(options, round_manager)

    # This task uses JvmDependencyAnalyzer as a helper, get its product needs
    JvmDependencyAnalyzer.prepare(options, round_manager)

    round_manager.require_data('compile_classpath')
    round_manager.require_data('ivy_cache_dir')
    round_manager.require_data('ivy_resolve_symlink_map')

    # Require codegen we care about
    # TODO(John Sirois): roll this up in Task - if the list of labels we care about for a target
    # predicate to filter the full build graph is exposed, the requirement can be made automatic
    # and in turn codegen tasks could denote the labels they produce automating wiring of the
    # produce side
    round_manager.require_data('java')
    round_manager.require_data('scala')

    # Allow the deferred_sources_mapping to take place first
    round_manager.require_data('deferred_sources')

  # Subclasses must implement.
  # --------------------------
  _language = None
  _file_suffix = None

  @classmethod
  def name(cls):
    return cls._language

  @classmethod
  def get_args_default(cls, bootstrap_option_values):
    """Override to set default for --args option.

    :param bootstrap_option_values: The values of the "bootstrap options" (e.g., pants_workdir).
                                    Implementations can use these when generating the default.
                                    See src/python/pants/options/options_bootstrapper.py for
                                    details.
    """
    return ()

  @classmethod
  def get_warning_args_default(cls):
    """Override to set default for --warning-args option."""
    return ()

  @classmethod
  def get_no_warning_args_default(cls):
    """Override to set default for --no-warning-args option."""
    return ()

  @property
  def config_section(self):
    return self.options_scope

  def select(self, target):
    return target.has_sources(self._file_suffix)

  def create_analysis_tools(self):
    """Returns an AnalysisTools implementation.

    Subclasses must implement.
    """
    raise NotImplementedError()

  def compile(self, args, classpath, sources, classes_output_dir, analysis_file):
    """Invoke the compiler.

    Must raise TaskError on compile failure.

    Subclasses must implement."""
    raise NotImplementedError()

  # Subclasses may override.
  # ------------------------
  def extra_compile_time_classpath_elements(self):
    """Extra classpath elements common to all compiler invocations.

    E.g., jars for compiler plugins.
    """
    return []

  def extra_products(self, target):
    """Any extra, out-of-band products created for a target.

    E.g., targets that produce scala compiler plugins produce an info file.
    Returns a list of pairs (root, [absolute paths of files under root]).
    """
    return []

  def post_process(self, relevant_targets):
    """Any extra post-execute work."""
    pass

  # Common code.
  # ------------
  @staticmethod
  def _analysis_for_target(analysis_dir, target):
    return os.path.join(analysis_dir, target.id + '.analysis')

  @staticmethod
  def _portable_analysis_for_target(analysis_dir, target):
    return JvmCompile._analysis_for_target(analysis_dir, target) + '.portable'

  def __init__(self, *args, **kwargs):
    super(JvmCompile, self).__init__(*args, **kwargs)

    self._strategy = JvmCompileStrategy(self.context, self.get_options(), self.workdir)

    # Various working directories.
    self._analysis_dir = os.path.join(self.workdir, 'analysis')
    self._target_sources_dir = os.path.join(self.workdir, 'target_sources')

    # We can't create analysis tools until after construction.
    self._lazy_analysis_tools = None

    # JVM options for running the compiler.
    self._jvm_options = self.get_options().jvm_options

    self._args = list(self.get_options().args)
    if self.get_options().warnings:
      self._args.extend(self.get_options().warning_args)
    else:
      self._args.extend(self.get_options().no_warning_args)

    self._upstream_class_to_path = None  # Computed lazily as needed.
    self.setup_artifact_cache()

    # Map of target -> list of sources (relative to buildroot), for all targets in all chunks.
    # Populated in prepare_execute().
    self._sources_by_target = None

  def _jvm_fingerprint_strategy(self):
    # Use a fingerprint strategy that allows us to also include java/scala versions.
    return JvmFingerprintStrategy(self.platform_version_info())

  def platform_version_info(self):
    """
    Provides extra platform information such as java version that will be used
    in the fingerprinter. This in turn ensures different platform versions create different
    cache artifacts.

    Sublclasses should override this and return a list of version info.
    """
    return None

  def pre_execute(self):
    # Only create these working dirs during execution phase, otherwise, they
    # would be wiped out by clean-all goal/task if it's specified.
    self._strategy.pre_execute()
    safe_mkdir(self._target_sources_dir)

    # TODO(John Sirois): Ensuring requested product maps are available - if empty - should probably
    # be lifted to Task infra.

    # In case we have no relevant targets and return early create the requested product maps.
    self._create_empty_products()

  def prepare_execute(self, chunks):
    all_targets = list(itertools.chain(*chunks))

    # Target -> sources (relative to buildroot).
    # TODO(benjy): Should sources_by_target be available in all Tasks?
    self._sources_by_target = self._compute_current_sources_by_target(all_targets)

    # Invoke the strategy's prepare_execute to prune analysis.
    cache_manager = self.create_cache_manager(invalidate_dependents=True,
                                              fingerprint_strategy=self._jvm_fingerprint_strategy())
    
    self._strategy.prepare_execute(cache_manager, self._sources_by_target, all_targets)

  # TODO(benjy): Break this monstrosity up? Previous attempts to do so
  #              turned out to be more trouble than it was worth.
  def execute_chunk(self, relevant_targets):
    # TODO(benjy): Add a pre-execute goal for injecting deps into targets, so e.g.,
    # we can inject a dep on the scala runtime library and still have it ivy-resolve.

    if not relevant_targets:
      return

    # Target -> sources (relative to buildroot), for just this chunk's targets.
    sources_by_target = self._sources_for_targets(relevant_targets)

    self._strategy.execute_chunk(sources_by_target, self._jvm_fingerprint_strategy(), relevant_targets)

    self.post_process(relevant_targets)

  def check_artifact_cache(self, vts):
    # Special handling for scala analysis files. Class files are retrieved directly into their
    # final locations in the global classes dir.

    def post_process_cached_vts(cached_vts):
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
        analysis_file = JvmCompile._analysis_for_target(self._analysis_tmpdir, target)
        portable_analysis_file = JvmCompile._portable_analysis_for_target(self._analysis_tmpdir,
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
            self._record_sources_by_target(target, sources)

          # Everything's good so move the merged analysis to its final location.
          if os.path.exists(tmp_analysis):
            self.move(tmp_analysis, self._analysis_file)

    self._ensure_analysis_tmpdir()
    return self.do_check_artifact_cache(vts, post_process_cached_vts=post_process_cached_vts)

  def _write_to_artifact_cache(self, analysis_file, vts, sources_by_target):
    vt_by_target = dict([(vt.target, vt) for vt in vts.versioned_targets])

    vts_targets = [t for t in vts.targets if not t.has_label('no_cache')]

    split_analysis_files = [
        JvmCompile._analysis_for_target(self._analysis_tmpdir, t) for t in vts_targets]
    portable_split_analysis_files = [
        JvmCompile._portable_analysis_for_target(self._analysis_tmpdir, t) for t in vts_targets]

    # Set up args for splitting the analysis into per-target files.
    splits = zip([sources_by_target.get(t, []) for t in vts_targets], split_analysis_files)
    splits_args_tuples = [(analysis_file, splits)]

    # Set up args for rebasing the splits.
    relativize_args_tuples = zip(split_analysis_files, portable_split_analysis_files)

    # Set up args for artifact cache updating.
    vts_artifactfiles_pairs = []
    classes_by_source = self._compute_classes_by_source(analysis_file)
    resources_by_target = self.context.products.get_data('resources_by_target')
    for target, sources in sources_by_target.items():
      if target.has_label('no_cache'):
        continue
      artifacts = []
      if resources_by_target is not None:
        for _, paths in resources_by_target[target].abs_paths():
          artifacts.extend(paths)
      for source in sources:
        classes = classes_by_source.get(source, [])
        artifacts.extend(classes)

      vt = vt_by_target.get(target)
      if vt is not None:
        # NOTE: analysis_file doesn't exist yet.
        vts_artifactfiles_pairs.append(
            (vt,
             artifacts + [JvmCompile._portable_analysis_for_target(self._analysis_tmpdir, target)]))

    update_artifact_cache_work = self.get_update_artifact_cache_work(vts_artifactfiles_pairs)
    if update_artifact_cache_work:
      work_chain = [
        Work(self._analysis_tools.split_to_paths, splits_args_tuples, 'split'),
        Work(self._analysis_tools.relativize, relativize_args_tuples, 'relativize'),
        update_artifact_cache_work
      ]
      self.context.submit_background_work_chain(work_chain, parent_workunit_name='cache')

  def _compute_classes_by_source(self, analysis_file=None):
    """Compute src->classes.

    Srcs are relative to buildroot. Classes are absolute paths.
    """
    if analysis_file is None:
      analysis_file = self._analysis_file

    if not os.path.exists(analysis_file):
      return {}
    buildroot = get_buildroot()
    products = self._analysis_parser.parse_products_from_path(analysis_file)
    classes_by_src = {}
    for src, classes in products.items():
      relsrc = os.path.relpath(src, buildroot)
      classes_by_src[relsrc] = classes
    return classes_by_src

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

  def _record_sources_by_target(self, target, sources):
    # Record target -> source mapping for future use.
    with open(os.path.join(self._target_sources_dir, target.identifier), 'w') as outfile:
      for src in sources:
        outfile.write(os.path.join(get_buildroot(), src))
        outfile.write('\n')

  def _compute_current_sources_by_target(self, targets):
    """Returns map target -> list of sources (relative to buildroot)."""
    def calculate_sources(target):
      sources = [s for s in target.sources_relative_to_buildroot() if s.endswith(self._file_suffix)]
      # TODO: Make this less hacky. Ideally target.java_sources will point to sources, not targets.
      if hasattr(target, 'java_sources') and target.java_sources:
        sources.extend(self._resolve_target_sources(target.java_sources, '.java'))
      return sources
    return dict([(t, calculate_sources(t)) for t in targets])

  def _resolve_target_sources(self, target_sources, extension=None):
    """Given a list of pants targets, extract their sources as a list.

    Filters against the extension if given and optionally returns the paths relative to the target
    base.
    """
    resolved_sources = []
    for target in target_sources:
      if target.has_sources():
        resolved_sources.extend(target.sources_relative_to_buildroot())
    return resolved_sources

  def _compute_classpath_elements_by_class(self, classpath):
    # Don't consider loose classes dirs in our classes dir. Those will be considered
    # separately, by looking at products.
    def non_product(path):
      return path != self._classes_dir

    if self._upstream_class_to_path is None:
      self._upstream_class_to_path = {}
      classpath_entries = filter(non_product, classpath)
      for cp_entry in self.find_all_bootstrap_jars() + classpath_entries:
        # Per the classloading spec, a 'jar' in this context can also be a .zip file.
        if os.path.isfile(cp_entry) and ((cp_entry.endswith('.jar') or cp_entry.endswith('.zip'))):
          with open_zip64(cp_entry, 'r') as jar:
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

  def find_all_bootstrap_jars(self):
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

  @property
  def _analysis_tools(self):
    if self._lazy_analysis_tools is None:
      self._lazy_analysis_tools = self.create_analysis_tools()
    return self._lazy_analysis_tools

  @property
  def _analysis_parser(self):
    return self._analysis_tools.parser

  @property
  def ivy_cache_dir(self):
    ret = self.context.products.get_data('ivy_cache_dir')
    if ret is None:
      raise TaskError('ivy_cache_dir product accessed before it was created.')
    return ret

  def _sources_for_targets(self, targets):
    """Returns a map target->sources for the specified targets."""
    if self._sources_by_target is None:
      raise TaskError('self._sources_by_target not computed yet.')
    return dict((t, self._sources_by_target.get(t, [])) for t in targets)

  def _create_empty_products(self):
    make_products = lambda: defaultdict(MultipleRootedProducts)
    if self.context.products.is_required_data('classes_by_source'):
      self.context.products.safe_create_data('classes_by_source', make_products)

    # Whether or not anything else requires resources_by_target, this task
    # uses it internally.
    self.context.products.safe_create_data('resources_by_target', make_products)

    # JvmDependencyAnalyzer uses classes_by_target within this run
    self.context.products.safe_create_data('classes_by_target', make_products)

  def _resources_by_class_file(self, class_file_name, resource_mapping):
    assert class_file_name.endswith(".class")
    assert class_file_name.startswith(self.workdir)
    class_file_name = class_file_name[len(self._classes_dir) + 1:-len(".class")]
    class_name = class_file_name.replace("/", ".")
    return resource_mapping.get(class_name, [])
