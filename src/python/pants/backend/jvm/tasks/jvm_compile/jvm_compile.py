# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import itertools
import os
import shutil
import sys
from collections import OrderedDict, defaultdict
from hashlib import sha1

from pants.backend.core.tasks.group_task import GroupMember
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.jvm_compile.compile_context import CompileContext
from pants.backend.jvm.tasks.jvm_compile.execution_graph import (ExecutionFailure, ExecutionGraph,
                                                                 Job)
from pants.backend.jvm.tasks.jvm_compile.resource_mapping import ResourceMapping
from pants.backend.jvm.tasks.nailgun_task import NailgunTaskBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import TaskIdentityFingerprintStrategy
from pants.base.worker_pool import Work, WorkerPool
from pants.base.workunit import WorkUnitLabel
from pants.goal.products import MultipleRootedProducts
from pants.option.custom_types import list_option
from pants.reporting.reporting_utils import items_to_report_element
from pants.util.dirutil import fast_relpath, safe_mkdir, safe_rmtree, safe_walk
from pants.util.fileutil import atomic_copy, create_size_estimators


class CacheHitCallback(object):
  """A serializable cache hit callback that cleans the class directory prior to cache extraction.

  This class holds onto class directories rather than CompileContexts because CompileContexts
  aren't picklable.
  """

  def __init__(self, cache_key_to_class_dir):
    self._key_to_classes_dir = cache_key_to_class_dir

  def __call__(self, cache_key):
    class_dir = self._key_to_classes_dir.get(cache_key)
    if class_dir:
      safe_mkdir(class_dir, clean=True)


class ResolvedJarAwareTaskIdentityFingerprintStrategy(TaskIdentityFingerprintStrategy):
  """Task fingerprint strategy that also includes the resolved coordinates of dependent jars."""

  def __init__(self, task, compile_classpath):
    super(ResolvedJarAwareTaskIdentityFingerprintStrategy, self).__init__(task)
    self._compile_classpath = compile_classpath

  def _build_hasher(self, target):
    hasher = super(ResolvedJarAwareTaskIdentityFingerprintStrategy, self)._build_hasher(target)
    if isinstance(target, JarLibrary):
      # NB: Collects only the jars for the current jar_library, and hashes them to ensure that both
      # the resolved coordinates, and the requested coordinates are used. This ensures that if a
      # source file depends on a library with source compatible but binary incompatible signature
      # changes between versions, that you won't get runtime errors due to using an artifact built
      # against a binary incompatible version resolved for a previous compile.
      classpath_entries = self._compile_classpath.get_artifact_classpath_entries_for_targets(
        [target], transitive=False)
      for _, entry in classpath_entries:
        hasher.update(str(entry.coordinate))
    return hasher

  def __hash__(self):
    return hash((type(self), self._task.fingerprint))

  def __eq__(self, other):
    return (isinstance(other, ResolvedJarAwareTaskIdentityFingerprintStrategy) and
            super(ResolvedJarAwareTaskIdentityFingerprintStrategy, self).__eq__(other))


class JvmCompile(NailgunTaskBase, GroupMember):
  """A common framework for JVM compilation.

  To subclass for a specific JVM language, implement the static values and methods
  mentioned below under "Subclasses must implement".
  """

  size_estimators = create_size_estimators()

  @classmethod
  def size_estimator_by_name(cls, estimation_strategy_name):
    return cls.size_estimators[estimation_strategy_name]

  @staticmethod
  def _analysis_for_target(analysis_dir, target):
    return os.path.join(analysis_dir, target.id + '.analysis')

  @staticmethod
  def _portable_analysis_for_target(analysis_dir, target):
    return JvmCompile._analysis_for_target(analysis_dir, target) + '.portable'

  @classmethod
  def register_options(cls, register):
    super(JvmCompile, cls).register_options(register)
    register('--jvm-options', advanced=True, type=list_option, default=[],
             help='Run the compiler with these JVM options.')

    register('--args', advanced=True, action='append',
             default=list(cls.get_args_default(register.bootstrap)), fingerprint=True,
             help='Pass these args to the compiler.')

    register('--confs', advanced=True, type=list_option, default=['default'],
             help='Compile for these Ivy confs.')

    # TODO: Stale analysis should be automatically ignored via Task identities:
    # https://github.com/pantsbuild/pants/issues/1351
    register('--clear-invalid-analysis', advanced=True, default=False, action='store_true',
             help='When set, any invalid/incompatible analysis files will be deleted '
                  'automatically.  When unset, an error is raised instead.')

    register('--warnings', default=True, action='store_true',
             help='Compile with all configured warnings enabled.')

    register('--warning-args', advanced=True, action='append',
             default=list(cls.get_warning_args_default()),
             help='Extra compiler args to use when warnings are enabled.')

    register('--no-warning-args', advanced=True, action='append',
             default=list(cls.get_no_warning_args_default()),
             help='Extra compiler args to use when warnings are disabled.')

    register('--delete-scratch', advanced=True, default=True, action='store_true',
             help='Leave intermediate scratch files around, for debugging build problems.')

    register('--worker-count', advanced=True, type=int, default=1,
             help='The number of concurrent workers to use when '
                  'compiling with {task}.'.format(task=cls._name))

    register('--size-estimator', advanced=True,
             choices=list(cls.size_estimators.keys()), default='filesize',
             help='The method of target size estimation.')

    register('--capture-log', advanced=True, action='store_true', default=False,
             fingerprint=True,
             help='Capture compilation output to per-target logs.')

  @classmethod
  def product_types(cls):
    raise TaskError('Expected to be installed in GroupTask, which has its own '
                    'product_types implementation.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(JvmCompile, cls).prepare(options, round_manager)

    round_manager.require_data('compile_classpath')

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
  _name = None
  _file_suffix = None
  _supports_concurrent_execution = None

  @classmethod
  def task_subsystems(cls):
    # NB(gmalmquist): This is only used to make sure the JvmTargets get properly fingerprinted.
    # See: java_zinc_compile_jvm_platform_integration#test_compile_stale_platform_settings.
    return super(JvmCompile, cls).task_subsystems() + (JvmPlatform,)

  @classmethod
  def name(cls):
    return cls._name

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

  def select_source(self, source_file_path):
    """Source predicate for this task."""
    return source_file_path.endswith(self._file_suffix)

  def create_analysis_tools(self):
    """Returns an AnalysisTools implementation.

    Subclasses must implement.
    """
    raise NotImplementedError()

  def compile(self, args, classpath, sources, classes_output_dir, upstream_analysis, analysis_file,
              log_file, settings):
    """Invoke the compiler.

    Must raise TaskError on compile failure.

    Subclasses must implement.
    :param list args: Arguments to the compiler (such as jmake or zinc).
    :param list classpath: List of classpath entries.
    :param list sources: Source files.
    :param str classes_output_dir: Where to put the compiled output.
    :param upstream_analysis:
    :param analysis_file: Where to write the compile analysis.
    :param log_file: Where to write logs.
    :param JvmPlatformSettings settings: platform settings determining the -source, -target, etc for
      javac to use.
    """
    raise NotImplementedError()

  # Subclasses may override.
  # ------------------------
  def extra_compile_time_classpath_elements(self):
    """Extra classpath elements common to all compiler invocations.

    E.g., jars for compiler plugins.

    These are added at the end of the classpath, after any dependencies, so that if they
    overlap with any explicit dependencies, the compiler sees those first.  This makes
    missing dependency accounting much simpler.
    """
    return []

  def extra_products(self, target):
    """Any extra, out-of-band resources created for a target.

    E.g., targets that produce scala compiler plugins or annotation processor files
    produce an info file. The resources will be added to the compile_classpath, and
    made available in resources_by_target.
    Returns a list of pairs (root, [absolute paths of files under root]).
    """
    return []

  def __init__(self, *args, **kwargs):
    super(JvmCompile, self).__init__(*args, **kwargs)
    self._targets_to_compile_settings = None

    # JVM options for running the compiler.
    self._jvm_options = self.get_options().jvm_options

    self._args = list(self.get_options().args)
    if self.get_options().warnings:
      self._args.extend(self.get_options().warning_args)
    else:
      self._args.extend(self.get_options().no_warning_args)

    # The ivy confs for which we're building.
    self._confs = self.get_options().confs

    # Maps CompileContext --> dict of upstream class to paths.
    self._upstream_class_to_paths = {}

    # Mapping of relevant (as selected by the predicate) sources by target.
    self._sources_by_target = None
    self._sources_predicate = self.select_source

    # Various working directories.
    self._analysis_dir = os.path.join(self.workdir, 'isolated-analysis')
    self._classes_dir = os.path.join(self.workdir, 'isolated-classes')
    self._logs_dir = os.path.join(self.workdir, 'isolated-logs')
    self._jars_dir = os.path.join(self.workdir, 'jars')

    self._capture_log = self.get_options().capture_log
    self._delete_scratch = self.get_options().delete_scratch
    self._clear_invalid_analysis = self.get_options().clear_invalid_analysis

    try:
      worker_count = self.get_options().worker_count
    except AttributeError:
      # tasks that don't support concurrent execution have no worker_count registered
      worker_count = 1
    self._worker_count = worker_count

    self._size_estimator = self.size_estimator_by_name(self.get_options().size_estimator)

    self._worker_pool = None

    self._analysis_tools = self.create_analysis_tools()

  @property
  def _analysis_parser(self):
    return self._analysis_tools.parser

  def _fingerprint_strategy(self, classpath_products):
    return ResolvedJarAwareTaskIdentityFingerprintStrategy(self, classpath_products)

  def ensure_analysis_tmpdir(self):
    """Work in a tmpdir so we don't stomp the main analysis files on error.

    A temporary, but well-known, dir in which to munge analysis/dependency files in before
    caching. It must be well-known so we know where to find the files when we retrieve them from
    the cache. The tmpdir is cleaned up in a shutdown hook, because background work
    may need to access files we create there even after this method returns
    :return: path of temporary analysis directory
    """
    analysis_tmpdir = os.path.join(self._workdir, 'analysis_tmpdir')
    if self._delete_scratch:
      self.context.background_worker_pool().add_shutdown_hook(
        lambda: safe_rmtree(analysis_tmpdir))
    safe_mkdir(analysis_tmpdir)
    return analysis_tmpdir

  def pre_execute(self):
    # Only create these working dirs during execution phase, otherwise, they
    # would be wiped out by clean-all goal/task if it's specified.
    self.analysis_tmpdir = self.ensure_analysis_tmpdir()
    safe_mkdir(self._analysis_dir)
    safe_mkdir(self._classes_dir)
    safe_mkdir(self._logs_dir)
    safe_mkdir(self._jars_dir)

    # TODO(John Sirois): Ensuring requested product maps are available - if empty - should probably
    # be lifted to Task infra.

    # In case we have no relevant targets and return early create the requested product maps.
    self._create_empty_products()

  def prepare_execute(self, chunks):
    relevant_targets = list(itertools.chain(*chunks))

    # Target -> sources (relative to buildroot).
    # TODO(benjy): Should sources_by_target be available in all Tasks?
    self._sources_by_target = self._compute_sources_by_target(relevant_targets)

    # Update the classpath by adding relevant target's classes directories to its classpath.
    compile_classpaths = self.context.products.get_data('compile_classpath')

    with self.context.new_workunit('validate-{}-analysis'.format(self._name)):
      for target in relevant_targets:
        cc = self.compile_context(target)
        safe_mkdir(cc.classes_dir)
        compile_classpaths.add_for_target(target, [(conf, cc.classes_dir) for conf in self._confs])
        self.validate_analysis(cc.analysis_file)

    # This ensures the workunit for the worker pool is set
    with self.context.new_workunit('isolation-{}-pool-bootstrap'.format(self._name)) \
            as workunit:
      # This uses workunit.parent as the WorkerPool's parent so that child workunits
      # of different pools will show up in order in the html output. This way the current running
      # workunit is on the bottom of the page rather than possibly in the middle.
      self._worker_pool = WorkerPool(workunit.parent,
                                     self.context.run_tracker,
                                     self._worker_count)

  def compile_context(self, target):
    analysis_file = JvmCompile._analysis_for_target(self._analysis_dir, target)
    classes_dir = os.path.join(self._classes_dir, target.id)
    # Generate a short unique path for the jar to allow for shorter classpaths.
    #   TODO: likely unnecessary after https://github.com/pantsbuild/pants/issues/1988
    jar_file = os.path.join(self._jars_dir, '{}.jar'.format(sha1(target.id).hexdigest()[:12]))
    return CompileContext(target,
                          analysis_file,
                          classes_dir,
                          jar_file,
                          self._sources_for_target(target))

  def execute_chunk(self, relevant_targets):
    if not relevant_targets:
      return

    classpath_product = self.context.products.get_data('compile_classpath')
    fingerprint_strategy = self._fingerprint_strategy(classpath_product)
    # Invalidation check. Everything inside the with block must succeed for the
    # invalid targets to become valid.
    partition_size_hint, locally_changed_targets = (0, None)
    with self.invalidated(relevant_targets,
                          invalidate_dependents=True,
                          partition_size_hint=partition_size_hint,
                          locally_changed_targets=locally_changed_targets,
                          fingerprint_strategy=fingerprint_strategy,
                          topological_order=True) as invalidation_check:
      if invalidation_check.invalid_vts:
        # Find the invalid targets for this chunk.
        invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]

        # Register products for all the valid targets.
        # We register as we go, so dependency checking code can use this data.
        valid_targets = [vt.target for vt in invalidation_check.all_vts if vt.valid]
        valid_compile_contexts = [self.compile_context(t) for t in valid_targets]
        self._register_vts(valid_compile_contexts)

        # Execute compilations for invalid targets.
        check_vts = (self.check_artifact_cache
            if self.artifact_cache_reads_enabled() else None)
        update_artifact_cache_vts_work = (self.get_update_artifact_cache_work
            if self.artifact_cache_writes_enabled() else None)
        self.compile_chunk(invalidation_check,
                           self.context.targets(),
                           relevant_targets,
                           invalid_targets,
                           self.extra_compile_time_classpath_elements(),
                           check_vts,
                           self._compile_vts,
                           self._register_vts,
                           update_artifact_cache_vts_work)
      else:
        # Nothing to build. Register products for all the targets in one go.
        self._register_vts([self.compile_context(t) for t in relevant_targets])

  def compile_chunk(self,
                    invalidation_check,
                    all_targets,
                    relevant_targets,
                    invalid_targets,
                    extra_compile_time_classpath_elements,
                    check_vts,
                    compile_vts,
                    register_vts,
                    update_artifact_cache_vts_work):
    """Executes compilations for the invalid targets contained in a single chunk."""
    assert invalid_targets, "compile_chunk should only be invoked if there are invalid targets."
    # Get the classpath generated by upstream JVM tasks and our own prepare_compile().
    compile_classpaths = self.context.products.get_data('compile_classpath')

    extra_compile_time_classpath = self._compute_extra_classpath(
        extra_compile_time_classpath_elements)

    compile_contexts = self._create_compile_contexts_for_targets(all_targets)

    # Now create compile jobs for each invalid target one by one.
    jobs = self._create_compile_jobs(compile_classpaths,
                                     compile_contexts,
                                     extra_compile_time_classpath,
                                     invalid_targets,
                                     invalidation_check.invalid_vts_partitioned,
                                     check_vts,
                                     compile_vts,
                                     register_vts,
                                     update_artifact_cache_vts_work)

    exec_graph = ExecutionGraph(jobs)
    try:
      exec_graph.execute(self._worker_pool, self.context.log)
    except ExecutionFailure as e:
      raise TaskError("Compilation failure: {}".format(e))

  def finalize_execute(self, chunks):
    targets = list(itertools.chain(*chunks))
    # Replace the classpath entry for each target with its jar'd representation.
    compile_classpaths = self.context.products.get_data('compile_classpath')
    for target in targets:
      cc = self.compile_context(target)
      for conf in self._confs:
        compile_classpaths.remove_for_target(target, [(conf, cc.classes_dir)])
        compile_classpaths.add_for_target(target, [(conf, cc.jar_file)])

  def _compile_vts(self, vts, sources, analysis_file, upstream_analysis, classpath, outdir,
                   log_file, progress_message, settings):
    """Compiles sources for the given vts into the given output dir.

    vts - versioned target set
    sources - sources for this target set
    analysis_file - the analysis file to manipulate
    classpath - a list of classpath entries
    outdir - the output dir to send classes to

    May be invoked concurrently on independent target sets.

    Postcondition: The individual targets in vts are up-to-date, as if each were
                   compiled individually.
    """
    if not sources:
      self.context.log.warn('Skipping {} compile for targets with no sources:\n  {}'
                            .format(self.name(), vts.targets))
    else:
      # Do some reporting.
      self.context.log.info(
        'Compiling ',
        items_to_report_element(sources, '{} source'.format(self.name())),
        ' in ',
        items_to_report_element([t.address.reference() for t in vts.targets], 'target'),
        ' (',
        progress_message,
        ').')
      with self.context.new_workunit('compile', labels=[WorkUnitLabel.COMPILER]):
        # The compiler may delete classfiles, then later exit on a compilation error. Then if the
        # change triggering the error is reverted, we won't rebuild to restore the missing
        # classfiles. So we force-invalidate here, to be on the safe side.
        vts.force_invalidate()
        self.compile(self._args, classpath, sources, outdir, upstream_analysis, analysis_file,
                     log_file, settings)

  def check_artifact_cache(self, vts):
    post_process_cached_vts = lambda cvts: self.post_process_cached_vts(cvts)
    cache_hit_callback = self.create_cache_hit_callback(vts)
    return self.do_check_artifact_cache(vts,
                                        post_process_cached_vts=post_process_cached_vts,
                                        cache_hit_callback=cache_hit_callback)

  def create_cache_hit_callback(self, vts):
    cache_key_to_classes_dir = {v.cache_key: self.compile_context(v.target).classes_dir
                                for v in vts}
    return CacheHitCallback(cache_key_to_classes_dir)

  def post_process_cached_vts(self, cached_vts):
    """Localizes the fetched analysis for targets we found in the cache.

    This is the complement of `_write_to_artifact_cache`.
    """
    compile_contexts = []
    for vt in cached_vts:
      for target in vt.targets:
        compile_contexts.append(self.compile_context(target))

    for compile_context in compile_contexts:
      portable_analysis_file = JvmCompile._portable_analysis_for_target(
          self._analysis_dir, compile_context.target)
      if os.path.exists(portable_analysis_file):
        self._analysis_tools.localize(portable_analysis_file, compile_context.analysis_file)

  def _create_empty_products(self):
    make_products = lambda: defaultdict(MultipleRootedProducts)
    if self.context.products.is_required_data('classes_by_source'):
      self.context.products.safe_create_data('classes_by_source', make_products)

    # Whether or not anything else requires resources_by_target, this task
    # uses it internally.
    self.context.products.safe_create_data('resources_by_target', make_products)

    # JvmDependencyCheck uses classes_by_target
    self.context.products.safe_create_data('classes_by_target', make_products)

    self.context.products.safe_create_data('product_deps_by_src', dict)

  def compute_classes_by_source(self, compile_contexts):
    """Compute a map of (context->(src->classes)) for the given compile_contexts.

    It's possible (although unfortunate) for multiple targets to own the same sources, hence
    the top level division. Srcs are relative to buildroot. Classes are absolute paths.

    Returning classes with 'None' as their src indicates that the compiler analysis indicated
    that they were un-owned. This case is triggered when annotation processors generate
    classes (or due to bugs in classfile tracking in zinc/jmake.)
    """
    buildroot = get_buildroot()
    # Build a mapping of srcs to classes for each context.
    classes_by_src_by_context = defaultdict(dict)
    for compile_context in compile_contexts:
      # Walk the context's jar to build a set of unclaimed classfiles.
      unclaimed_classes = set()
      with compile_context.open_jar(mode='r') as jar:
        for name in jar.namelist():
          if not name.endswith('/'):
            unclaimed_classes.add(os.path.join(compile_context.classes_dir, name))

      # Grab the analysis' view of which classfiles were generated.
      classes_by_src = classes_by_src_by_context[compile_context]
      if os.path.exists(compile_context.analysis_file):
        products = self._analysis_parser.parse_products_from_path(compile_context.analysis_file,
                                                                  compile_context.classes_dir)
        for src, classes in products.items():
          relsrc = os.path.relpath(src, buildroot)
          classes_by_src[relsrc] = classes
          unclaimed_classes.difference_update(classes)

      # Any remaining classfiles were unclaimed by sources/analysis.
      classes_by_src[None] = list(unclaimed_classes)
    return classes_by_src_by_context

  def class_name_for_class_file(self, compile_context, class_file_name):
    if not class_file_name.endswith(".class"):
      return None
    assert class_file_name.startswith(compile_context.classes_dir)
    class_file_name = class_file_name[len(compile_context.classes_dir) + 1:-len(".class")]
    return class_file_name.replace("/", ".")

  def _register_vts(self, compile_contexts):
    classes_by_source = self.context.products.get_data('classes_by_source')
    classes_by_target = self.context.products.get_data('classes_by_target')
    compile_classpath = self.context.products.get_data('compile_classpath')
    resources_by_target = self.context.products.get_data('resources_by_target')
    product_deps_by_src = self.context.products.get_data('product_deps_by_src')

    # Register class products (and resources generated by annotation processors.)
    computed_classes_by_source_by_context = self.compute_classes_by_source(
        compile_contexts)
    resource_mapping = ResourceMapping(self._classes_dir)
    for compile_context in compile_contexts:
      computed_classes_by_source = computed_classes_by_source_by_context[compile_context]
      target = compile_context.target
      classes_dir = compile_context.classes_dir

      def add_products_by_target(files):
        for f in files:
          clsname = self.class_name_for_class_file(compile_context, f)
          if clsname:
            # Is a class.
            classes_by_target[target].add_abs_paths(classes_dir, [f])
            resources = resource_mapping.get(clsname, [])
            resources_by_target[target].add_abs_paths(classes_dir, resources)
          else:
            # Is a resource.
            resources_by_target[target].add_abs_paths(classes_dir, [f])

      # Collect classfiles (absolute) that were claimed by sources (relative)
      for source in compile_context.sources:
        classes = computed_classes_by_source.get(source, [])
        add_products_by_target(classes)
        if classes_by_source is not None:
          classes_by_source[source].add_abs_paths(classes_dir, classes)

      # And any that were not claimed by sources (NB: `None` map key.)
      unclaimed_classes = computed_classes_by_source.get(None, [])
      if unclaimed_classes:
        self.context.log.debug(
          items_to_report_element(unclaimed_classes, 'class'),
          ' not claimed by analysis for ',
          str(compile_context.target)
        )
        add_products_by_target(unclaimed_classes)

    for compile_context in compile_contexts:
      # Register resource products.
      extra_resources = self.extra_products(compile_context.target)
      # Add to resources_by_target (if it was requested).
      if resources_by_target is not None:
        target_resources = resources_by_target[compile_context.target]
        for root, abs_paths in extra_resources:
          target_resources.add_abs_paths(root, abs_paths)
      # And to the compile_classpath, to make them available within the next round.
      # TODO(stuhood): This is redundant with resources_by_target, but resources_by_target
      # are not available during compilation. https://github.com/pantsbuild/pants/issues/206
      entries = [(conf, root) for conf in self._confs for root, _ in extra_resources]
      compile_classpath.add_for_target(compile_context.target, entries)

      if self.context.products.is_required_data('product_deps_by_src'):
        product_deps_by_src[compile_context.target] = \
            self._analysis_parser.parse_deps_from_path(compile_context.analysis_file)

  def _create_compile_contexts_for_targets(self, targets):
    compile_contexts = OrderedDict()
    for target in targets:
      compile_context = self.compile_context(target)
      compile_contexts[target] = compile_context
    return compile_contexts

  def _compute_classpath_entries(self, compile_classpaths,
                                 target_closure,
                                 compile_context,
                                 extra_compile_time_classpath):
    # Generate a classpath specific to this compile and target.
    return ClasspathUtil.compute_classpath_for_target(compile_context.target, compile_classpaths,
                                                      extra_compile_time_classpath, self._confs,
                                                      target_closure)

  def _upstream_analysis(self, compile_contexts, classpath_entries):
    """Returns tuples of classes_dir->analysis_file for the closure of the target."""
    # Reorganize the compile_contexts by class directory.
    compile_contexts_by_directory = {}
    for compile_context in compile_contexts.values():
      compile_contexts_by_directory[compile_context.classes_dir] = compile_context
    # If we have a compile context for the target, include it.
    for entry in classpath_entries:
      if not entry.endswith('.jar'):
        compile_context = compile_contexts_by_directory.get(entry)
        if not compile_context:
          self.context.log.debug('Missing upstream analysis for {}'.format(entry))
        else:
          yield compile_context.classes_dir, compile_context.analysis_file

  def _capture_log_file(self, target):
    if self._capture_log:
      return os.path.join(self._logs_dir, "{}.log".format(target.id))
    return None

  def exec_graph_key_for_target(self, compile_target):
    return "compile({})".format(compile_target.address.spec)

  def _create_compile_jobs(self, compile_classpaths, compile_contexts, extra_compile_time_classpath,
                           invalid_targets, invalid_vts_partitioned, check_vts, compile_vts,
                           register_vts, update_artifact_cache_vts_work):
    def check_cache(vts):
      """Manually checks the artifact cache (usually immediately before compilation.)

      Returns true if the cache was hit successfully, indicating that no compilation is necessary.
      """
      if not check_vts:
        return False
      cached_vts, uncached_vts = check_vts([vts])
      if not cached_vts:
        self.context.log.debug('Missed cache during double check for {}'.format(vts.target.address.spec))
        return False
      assert cached_vts == [vts], (
          'Cache returned unexpected target: {} vs {}'.format(cached_vts, [vts])
      )
      self.context.log.info('Hit cache during double check for {}'.format(vts.target.address.spec))
      return True

    def work_for_vts(vts, compile_context, target_closure):
      progress_message = compile_context.target.address.spec
      cp_entries = self._compute_classpath_entries(compile_classpaths,
                                                   target_closure,
                                                   compile_context,
                                                   extra_compile_time_classpath)

      upstream_analysis = dict(self._upstream_analysis(compile_contexts, cp_entries))

      # Capture a compilation log if requested.
      log_file = self._capture_log_file(compile_context.target)

      # Double check the cache before beginning compilation
      if not check_cache(vts):
        # Mutate analysis within a temporary directory, and move it to the final location
        # on success.
        tmpdir = os.path.join(self.analysis_tmpdir, compile_context.target.id)
        safe_mkdir(tmpdir)
        tmp_analysis_file = self._analysis_for_target(
            tmpdir, compile_context.target)
        if os.path.exists(compile_context.analysis_file):
          shutil.copy(compile_context.analysis_file, tmp_analysis_file)
        target, = vts.targets
        compile_vts(vts,
                    compile_context.sources,
                    tmp_analysis_file,
                    upstream_analysis,
                    cp_entries,
                    compile_context.classes_dir,
                    log_file,
                    progress_message,
                    target.platform)
        atomic_copy(tmp_analysis_file, compile_context.analysis_file)

        # Jar the compiled output.
        self._create_context_jar(compile_context)

      # Update the products with the latest classes.
      register_vts([compile_context])

      # Kick off the background artifact cache write.
      if update_artifact_cache_vts_work:
        self._write_to_artifact_cache(vts, compile_context, update_artifact_cache_vts_work)

    jobs = []
    invalid_target_set = set(invalid_targets)
    for vts in invalid_vts_partitioned:
      assert len(vts.targets) == 1, ("Requested one target per partition, got {}".format(vts))

      # Invalidated targets are a subset of relevant targets: get the context for this one.
      compile_target = vts.targets[0]
      compile_context = compile_contexts[compile_target]
      compile_target_closure = compile_target.closure()

      # dependencies of the current target which are invalid for this chunk
      invalid_dependencies = (compile_target_closure & invalid_target_set) - [compile_target]

      jobs.append(Job(self.exec_graph_key_for_target(compile_target),
                      functools.partial(work_for_vts, vts, compile_context, compile_target_closure),
                      [self.exec_graph_key_for_target(target) for target in invalid_dependencies],
                      self._size_estimator(compile_context.sources),
                      # If compilation and analysis work succeeds, validate the vts.
                      # Otherwise, fail it.
                      on_success=vts.update,
                      on_failure=vts.force_invalidate))
    return jobs

  def _create_context_jar(self, compile_context):
    """Jar up the compile_context to its output jar location.

    TODO(stuhood): In the medium term, we hope to add compiler support for this step, which would
    allow the jars to be used as compile _inputs_ as well. Currently using jar'd compile outputs as
    compile inputs would make the compiler's analysis useless.
      see https://github.com/twitter-forks/sbt/tree/stuhood/output-jars
    """
    root = compile_context.classes_dir
    with compile_context.open_jar(mode='w') as jar:
      for abs_sub_dir, dirnames, filenames in safe_walk(root):
        for name in dirnames + filenames:
          abs_filename = os.path.join(abs_sub_dir, name)
          arcname = fast_relpath(abs_filename, root)
          jar.write(abs_filename, arcname)

  def _write_to_artifact_cache(self, vts, compile_context, get_update_artifact_cache_work):
    assert len(vts.targets) == 1
    assert vts.targets[0] == compile_context.target

    # Noop if the target is uncacheable.
    if (compile_context.target.has_label('no_cache')):
      return
    vt = vts.versioned_targets[0]

    # Set up args to relativize analysis in the background.
    portable_analysis_file = self._portable_analysis_for_target(
        self._analysis_dir, compile_context.target)
    relativize_args_tuple = (compile_context.analysis_file, portable_analysis_file)

    # Collect the artifacts for this target.
    artifacts = []

    def add_abs_products(p):
      if p:
        for _, paths in p.abs_paths():
          artifacts.extend(paths)
    # Resources.
    resources_by_target = self.context.products.get_data('resources_by_target')
    add_abs_products(resources_by_target.get(compile_context.target))
    # Classes.
    classes_by_target = self.context.products.get_data('classes_by_target')
    add_abs_products(classes_by_target.get(compile_context.target))
    # Log file.
    log_file = self._capture_log_file(compile_context.target)
    if log_file and os.path.exists(log_file):
      artifacts.append(log_file)
    # Jar.
    artifacts.append(compile_context.jar_file)

    # Get the 'work' that will publish these artifacts to the cache.
    # NB: the portable analysis_file won't exist until we finish.
    vts_artifactfiles_pair = (vt, artifacts + [portable_analysis_file])
    update_artifact_cache_work = get_update_artifact_cache_work([vts_artifactfiles_pair])

    # And execute it.
    if update_artifact_cache_work:
      work_chain = [
          Work(self._analysis_tools.relativize, [relativize_args_tuple], 'relativize'),
          update_artifact_cache_work
      ]
      self.context.submit_background_work_chain(work_chain, parent_workunit_name='cache')

  def validate_analysis(self, path):
    """Throws a TaskError for invalid analysis files."""
    try:
      self._analysis_parser.validate_analysis(path)
    except Exception as e:
      if self._clear_invalid_analysis:
        self.context.log.warn("Invalid analysis detected at path {} ... pants will remove these "
                              "automatically, but\nyou may experience spurious warnings until "
                              "clean-all is executed.\n{}".format(path, e))
        safe_delete(path)
      else:
        raise TaskError("An internal build directory contains invalid/mismatched analysis: please "
                        "run `clean-all` if your tools versions changed recently:\n{}".format(e))

  def _compute_sources_by_target(self, targets):
    """Computes and returns a map target->sources (relative to buildroot)."""
    def resolve_target_sources(target_sources):
      resolved_sources = []
      for target in target_sources:
        if target.has_sources():
          resolved_sources.extend(target.sources_relative_to_buildroot())
      return resolved_sources

    def calculate_sources(target):
      sources = [s for s in target.sources_relative_to_buildroot() if self._sources_predicate(s)]
      # TODO: Make this less hacky. Ideally target.java_sources will point to sources, not targets.
      if hasattr(target, 'java_sources') and target.java_sources:
        sources.extend(resolve_target_sources(target.java_sources))
      return sources
    return {t: calculate_sources(t) for t in targets}

  def _sources_for_targets(self, targets):
    """Returns a cached map of target->sources for the specified targets."""
    if self._sources_by_target is None:
      raise TaskError('self._sources_by_target not computed yet.')
    return {t: self._sources_by_target.get(t, []) for t in targets}

  def _sources_for_target(self, target):
    """Returns the cached sources for the given target."""
    if self._sources_by_target is None:
      raise TaskError('self._sources_by_target not computed yet.')
    return self._sources_by_target.get(target, [])

  def _compute_extra_classpath(self, extra_compile_time_classpath_elements):
    """Compute any extra compile-time-only classpath elements.

    TODO(benjy): Model compile-time vs. runtime classpaths more explicitly.
    TODO(benjy): Add a pre-execute goal for injecting deps into targets, so e.g.,
    we can inject a dep on the scala runtime library and still have it ivy-resolve.
    """
    def extra_compile_classpath_iter():
      for conf in self._confs:
        for jar in extra_compile_time_classpath_elements:
          yield (conf, jar)

    return list(extra_compile_classpath_iter())
