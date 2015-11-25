# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import hashlib
import itertools
import os
from collections import defaultdict

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.targets.resources import Resources
from pants.backend.core.tasks.group_task import GroupMember
from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.jvm_compile.compile_context import CompileContext
from pants.backend.jvm.tasks.jvm_compile.execution_graph import (ExecutionFailure, ExecutionGraph,
                                                                 Job)
from pants.backend.jvm.tasks.nailgun_task import NailgunTaskBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import TaskIdentityFingerprintStrategy
from pants.base.worker_pool import WorkerPool
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.target import Target
from pants.goal.products import MultipleRootedProducts
from pants.option.custom_types import list_option
from pants.reporting.reporting_utils import items_to_report_element
from pants.util.dirutil import fast_relpath, safe_delete, safe_mkdir, safe_walk
from pants.util.fileutil import create_size_estimators


class ResolvedJarAwareTaskIdentityFingerprintStrategy(TaskIdentityFingerprintStrategy):
  """Task fingerprint strategy that also includes the resolved coordinates of dependent jars."""

  def __init__(self, task, classpath_products):
    super(ResolvedJarAwareTaskIdentityFingerprintStrategy, self).__init__(task)
    self._classpath_products = classpath_products

  def _build_hasher(self, target):
    if isinstance(target, Resources):
      # Just do nothing, this kind of dependency shouldn't affect result's hash.
      return hashlib.sha1()

    hasher = super(ResolvedJarAwareTaskIdentityFingerprintStrategy, self)._build_hasher(target)
    if isinstance(target, JarLibrary):
      # NB: Collects only the jars for the current jar_library, and hashes them to ensure that both
      # the resolved coordinates, and the requested coordinates are used. This ensures that if a
      # source file depends on a library with source compatible but binary incompatible signature
      # changes between versions, that you won't get runtime errors due to using an artifact built
      # against a binary incompatible version resolved for a previous compile.
      classpath_entries = self._classpath_products.get_artifact_classpath_entries_for_targets(
        [target])
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

    register('--warnings', default=True, action='store_true', fingerprint=True,
             help='Compile with all configured warnings enabled.')

    register('--warning-args', advanced=True, action='append', fingerprint=True,
             default=list(cls.get_warning_args_default()),
             help='Extra compiler args to use when warnings are enabled.')

    register('--no-warning-args', advanced=True, action='append', fingerprint=True,
             default=list(cls.get_no_warning_args_default()),
             help='Extra compiler args to use when warnings are disabled.')

    register('--debug-symbols', default=False, action='store_true', fingerprint=True,
             help='Compile with debug symbol enabled.')

    register('--debug-symbol-args', advanced=True, action='append', fingerprint=True,
             default=['-C-g:lines,source,vars'],
             help='Extra args to enable debug symbol.')

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
    return super(JvmCompile, cls).task_subsystems() + (Java, JvmPlatform, ScalaPlatform)

  @classmethod
  def name(cls):
    return cls._name

  @property
  def compiler_plugin_types(cls):
    """A tuple of target types which are compiler plugins."""
    return ()

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
  def cache_target_dirs(self):
    return True

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
              log_file, settings, fatal_warnings):
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
    :param fatal_warnings: whether to convert compilation warnings to errors.
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

  def write_extra_resources(self, compile_context):
    """Writes any extra, out-of-band resources for a target to its classes directory.

    E.g., targets that produce scala compiler plugins or annotation processor files
    produce an info file. The resources will be added to the runtime_classpath.
    Returns a list of pairs (root, [absolute paths of files under root]).
    """
    pass

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

    if self.get_options().debug_symbols:
      self._args.extend(self.get_options().debug_symbol_args)

    # The ivy confs for which we're building.
    self._confs = self.get_options().confs

    # Determines which sources are relevant to this target.
    self._sources_predicate = self.select_source

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

  def pre_execute(self):
    # In case we have no relevant targets and return early create the requested product maps.
    self._create_empty_products()

  def prepare_execute(self, chunks):
    relevant_targets = list(itertools.chain(*chunks))

    # Clone the compile_classpath to the runtime_classpath.
    compile_classpath = self.context.products.get_data('compile_classpath')
    runtime_classpath = self.context.products.get_data('runtime_classpath', compile_classpath.copy)

    # This ensures the workunit for the worker pool is set
    with self.context.new_workunit('isolation-{}-pool-bootstrap'.format(self._name)) \
            as workunit:
      # This uses workunit.parent as the WorkerPool's parent so that child workunits
      # of different pools will show up in order in the html output. This way the current running
      # workunit is on the bottom of the page rather than possibly in the middle.
      self._worker_pool = WorkerPool(workunit.parent,
                                     self.context.run_tracker,
                                     self._worker_count)

  def _compile_context(self, target, target_workdir):
    analysis_file = JvmCompile._analysis_for_target(target_workdir, target)
    portable_analysis_file = JvmCompile._portable_analysis_for_target(target_workdir, target)
    classes_dir = os.path.join(target_workdir, 'classes')
    jar_file = os.path.join(target_workdir, 'z.jar')
    log_file = os.path.join(target_workdir, 'debug.log')
    strict_deps = self._compute_language_property(target, lambda x: x.strict_deps)
    return CompileContext(target,
                          analysis_file,
                          portable_analysis_file,
                          classes_dir,
                          jar_file,
                          log_file,
                          self._compute_sources_for_target(target),
                          strict_deps)

  def execute_chunk(self, relevant_targets):
    if not relevant_targets:
      return

    classpath_product = self.context.products.get_data('runtime_classpath')
    fingerprint_strategy = self._fingerprint_strategy(classpath_product)
    # Invalidation check. Everything inside the with block must succeed for the
    # invalid targets to become valid.
    with self.invalidated(relevant_targets,
                          invalidate_dependents=True,
                          partition_size_hint=0,
                          fingerprint_strategy=fingerprint_strategy,
                          topological_order=True) as invalidation_check:

      # Initialize the classpath for all targets.
      compile_contexts = {vt.target: self._compile_context(vt.target, vt.results_dir)
                          for vt in invalidation_check.all_vts}
      for cc in compile_contexts.values():
        classpath_product.add_for_target(cc.target,
                                         [(conf, cc.classes_dir) for conf in self._confs])

      # Register products for valid targets.
      valid_targets = [vt.target for vt in invalidation_check.all_vts if vt.valid]
      self._register_vts([compile_contexts[t] for t in valid_targets])

      # Build any invalid targets (which will register products in the background).
      if invalidation_check.invalid_vts:
        invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]

        self.compile_chunk(invalidation_check,
                           compile_contexts,
                           invalid_targets,
                           self.extra_compile_time_classpath_elements())

      # Once compilation has completed, replace the classpath entry for each target with
      # its jar'd representation.
      classpath_products = self.context.products.get_data('runtime_classpath')
      for cc in compile_contexts.values():
        for conf in self._confs:
          classpath_products.remove_for_target(cc.target, [(conf, cc.classes_dir)])
          classpath_products.add_for_target(cc.target, [(conf, cc.jar_file)])

  def compile_chunk(self,
                    invalidation_check,
                    compile_contexts,
                    invalid_targets,
                    extra_compile_time_classpath_elements):
    """Executes compilations for the invalid targets contained in a single chunk."""
    assert invalid_targets, "compile_chunk should only be invoked if there are invalid targets."

    # Prepare the output directory for each invalid target, and confirm that analysis is valid.
    for target in invalid_targets:
      cc = compile_contexts[target]
      safe_mkdir(cc.classes_dir)
      self.validate_analysis(cc.analysis_file)

    # Get the classpath generated by upstream JVM tasks and our own prepare_compile().
    classpath_products = self.context.products.get_data('runtime_classpath')

    extra_compile_time_classpath = self._compute_extra_classpath(
        extra_compile_time_classpath_elements)

    # Now create compile jobs for each invalid target one by one.
    jobs = self._create_compile_jobs(classpath_products,
                                     compile_contexts,
                                     extra_compile_time_classpath,
                                     invalid_targets,
                                     invalidation_check.invalid_vts_partitioned)

    exec_graph = ExecutionGraph(jobs)
    try:
      exec_graph.execute(self._worker_pool, self.context.log)
    except ExecutionFailure as e:
      raise TaskError("Compilation failure: {}".format(e))

  def _compile_vts(self, vts, sources, analysis_file, upstream_analysis, classpath, outdir,
                   log_file, progress_message, settings, fatal_warnings, counter):
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
      counter_val = str(counter()).rjust(counter.format_length(), b' ')
      counter_str = '[{}/{}] '.format(counter_val, counter.size)
      # Do some reporting.
      self.context.log.info(
        counter_str,
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
                     log_file, settings, fatal_warnings)

  def check_artifact_cache(self, vts):
    """Localizes the fetched analysis for targets we found in the cache."""
    def post_process(cached_vts):
      for vt in cached_vts:
        cc = self._compile_context(vt.target, vt.results_dir)
        safe_delete(cc.analysis_file)
        self._analysis_tools.localize(cc.portable_analysis_file, cc.analysis_file)
    return self.do_check_artifact_cache(vts, post_process_cached_vts=post_process)

  def _create_empty_products(self):
    if self.context.products.is_required_data('classes_by_source'):
      make_products = lambda: defaultdict(MultipleRootedProducts)
      self.context.products.safe_create_data('classes_by_source', make_products)

    if self.context.products.is_required_data('product_deps_by_src'):
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

  def classname_for_classfile(self, compile_context, class_file_name):
    assert class_file_name.startswith(compile_context.classes_dir)
    rel_classfile_path = class_file_name[len(compile_context.classes_dir) + 1:]
    return ClasspathUtil.classname_for_rel_classfile(rel_classfile_path)

  def _register_vts(self, compile_contexts):
    classes_by_source = self.context.products.get_data('classes_by_source')
    product_deps_by_src = self.context.products.get_data('product_deps_by_src')
    runtime_classpath = self.context.products.get_data('runtime_classpath')

    # Register a mapping between sources and classfiles (if requested).
    if classes_by_source is not None:
      ccbsbc = self.compute_classes_by_source(compile_contexts).items()
      for compile_context, computed_classes_by_source in ccbsbc:
        target = compile_context.target
        classes_dir = compile_context.classes_dir

        for source in compile_context.sources:
          classes = computed_classes_by_source.get(source, [])
          classes_by_source[source].add_abs_paths(classes_dir, classes)

    # Register classfile product dependencies (if requested).
    if product_deps_by_src is not None:
      for compile_context in compile_contexts:
        product_deps_by_src[compile_context.target] = \
            self._analysis_parser.parse_deps_from_path(compile_context.analysis_file)

  def _compute_strict_dependencies(self, target):
    """Compute the 'strict' compile target dependencies for the given target.

    Recursively resolves target aliases, and includes the transitive deps of compiler plugins,
    since compiletime is actually runtime for them.
    """
    def resolve(t):
      for declared in t.dependencies:
        if isinstance(declared, Dependencies) or type(declared) == Target:
          for r in resolve(declared):
            yield r
        elif isinstance(declared, self.compiler_plugin_types):
          for r in declared.closure(bfs=True):
            yield r
        else:
          yield declared

    yield target
    for dep in resolve(target):
      yield dep

  def _compute_classpath_entries(self,
                                 classpath_products,
                                 compile_context,
                                 extra_compile_time_classpath):
    # Generate a classpath specific to this compile and target.
    target = compile_context.target
    if compile_context.strict_deps:
      classpath_targets = list(self._compute_strict_dependencies(target))
      pruned = [t.address.spec for t in target.closure(bfs=True) if t not in classpath_targets]
      self.context.log.debug(
          'Using strict classpath for {}, which prunes the following dependencies: {}'.format(
            target.address.spec, pruned))
    else:
      classpath_targets = target.closure(bfs=True)
    return ClasspathUtil.compute_classpath(classpath_targets, classpath_products,
                                           extra_compile_time_classpath, self._confs)

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

  def exec_graph_key_for_target(self, compile_target):
    return "compile({})".format(compile_target.address.spec)

  def _create_compile_jobs(self, classpath_products, compile_contexts, extra_compile_time_classpath,
                           invalid_targets, invalid_vts_partitioned):
    def check_cache(vts):
      """Manually checks the artifact cache (usually immediately before compilation.)

      Returns true if the cache was hit successfully, indicating that no compilation is necessary.
      """
      if not self.artifact_cache_reads_enabled():
        return False
      cached_vts, uncached_vts = self.check_artifact_cache([vts])
      if not cached_vts:
        self.context.log.debug('Missed cache during double check for {}'
                               .format(vts.target.address.spec))
        return False
      assert cached_vts == [vts], (
          'Cache returned unexpected target: {} vs {}'.format(cached_vts, [vts])
      )
      self.context.log.info('Hit cache during double check for {}'.format(vts.target.address.spec))
      return True

    def should_compile_incrementally(vts):
      """Check to see if the compile should try to re-use the existing analysis.

      Returns true if we should try to compile the target incrementally.
      """
      if not vts.is_incremental:
        return False
      if not self._clear_invalid_analysis:
        return True
      return os.path.exists(compile_context.analysis_file)

    class Counter(object):
      def __init__(self, size, initial=0):
        self.size = size
        self.count = initial

      def __call__(self):
        self.count += 1
        return self.count

      def format_length(self):
        return len(str(self.size))

    counter = Counter(len(invalid_vts_partitioned))
    def work_for_vts(vts, compile_context):
      progress_message = compile_context.target.address.spec

      # Capture a compilation log if requested.
      log_file = compile_context.log_file if self._capture_log else None

      # Double check the cache before beginning compilation
      hit_cache = check_cache(vts)

      if not hit_cache:
        # Compute the compile classpath for this target.
        cp_entries = self._compute_classpath_entries(classpath_products,
                                                     compile_context,
                                                     extra_compile_time_classpath)
        # TODO: always provide transitive analysis, but not always all classpath entries?
        upstream_analysis = dict(self._upstream_analysis(compile_contexts, cp_entries))

        # Write analysis to a temporary file, and move it to the final location on success.
        tmp_analysis_file = "{}.tmp".format(compile_context.analysis_file)
        if should_compile_incrementally(vts):
          # If this is an incremental compile, rebase the analysis to our new classes directory.
          self._analysis_tools.rebase_from_path(compile_context.analysis_file,
                                                tmp_analysis_file,
                                                vts.previous_results_dir,
                                                vts.results_dir)
        else:
          # Otherwise, simply ensure that it is empty.
          safe_delete(tmp_analysis_file)
        target, = vts.targets
        fatal_warnings = fatal_warnings = self._compute_language_property(target, lambda x: x.fatal_warnings)
        self._compile_vts(vts,
                          compile_context.sources,
                          tmp_analysis_file,
                          upstream_analysis,
                          cp_entries,
                          compile_context.classes_dir,
                          log_file,
                          progress_message,
                          target.platform,
                          fatal_warnings,
                          counter)
        os.rename(tmp_analysis_file, compile_context.analysis_file)
        self._analysis_tools.relativize(compile_context.analysis_file, compile_context.portable_analysis_file)

        # Write any additional resources for this target to the target workdir.
        self.write_extra_resources(compile_context)

        # Jar the compiled output.
        self._create_context_jar(compile_context)

      # Update the products with the latest classes.
      self._register_vts([compile_context])

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
                      functools.partial(work_for_vts, vts, compile_context),
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

  def _compute_sources_for_target(self, target):
    """Computes and returns the sources (relative to buildroot) for the given target."""
    def resolve_target_sources(target_sources):
      resolved_sources = []
      for target in target_sources:
        if target.has_sources():
          resolved_sources.extend(target.sources_relative_to_buildroot())
      return resolved_sources

    sources = [s for s in target.sources_relative_to_buildroot() if self._sources_predicate(s)]
    # TODO: Make this less hacky. Ideally target.java_sources will point to sources, not targets.
    if hasattr(target, 'java_sources') and target.java_sources:
      sources.extend(resolve_target_sources(target.java_sources))
    return sources

  def _compute_language_property(self, target, selector):
    """Computes the a language property setting for the given target sources.

    :param target The target whose language property will be calculated.
    :param selector A function that takes a target or platform and returns the boolean value of the
                    property for that target or platform, or None if that target or platform does
                    not directly define the property.

    If the target does not override the language property, returns true iff the property
    is true for any of the matched languages for the target.
    """
    if selector(target) is not None:
      return selector(target)

    property = False
    if target.has_sources('.java'):
      property |= selector(Java.global_instance())
    if target.has_sources('.scala'):
      property |= selector(ScalaPlatform.global_instance())
    return property

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
