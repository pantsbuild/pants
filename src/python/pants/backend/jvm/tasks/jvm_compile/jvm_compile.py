# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import os
from collections import defaultdict
from multiprocessing import cpu_count

from twitter.common.collections import OrderedSet

from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.javac_plugin import JavacPlugin
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.jvm_compile.compile_context import CompileContext, DependencyContext
from pants.backend.jvm.tasks.jvm_compile.execution_graph import (ExecutionFailure, ExecutionGraph,
                                                                 Job)
from pants.backend.jvm.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.backend.jvm.tasks.nailgun_task import NailgunTaskBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import TaskIdentityFingerprintStrategy
from pants.base.worker_pool import WorkerPool
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.resources import Resources
from pants.build_graph.target_scopes import Scopes
from pants.goal.products import MultipleRootedProducts
from pants.reporting.reporting_utils import items_to_report_element
from pants.util.dirutil import fast_relpath, safe_delete, safe_mkdir, safe_rmtree, safe_walk
from pants.util.fileutil import create_size_estimators
from pants.util.memo import memoized_property


class ResolvedJarAwareTaskIdentityFingerprintStrategy(TaskIdentityFingerprintStrategy):
  """Task fingerprint strategy that also includes the resolved coordinates of dependent jars."""

  def __init__(self, task, classpath_products):
    super(ResolvedJarAwareTaskIdentityFingerprintStrategy, self).__init__(task)
    self._classpath_products = classpath_products

  def compute_fingerprint(self, target):
    if isinstance(target, Resources):
      # Just do nothing, this kind of dependency shouldn't affect result's hash.
      return None

    hasher = self._build_hasher(target)
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
    return hasher.hexdigest()

  def __hash__(self):
    return hash((type(self), self._task.fingerprint))

  def __eq__(self, other):
    return (isinstance(other, ResolvedJarAwareTaskIdentityFingerprintStrategy) and
            super(ResolvedJarAwareTaskIdentityFingerprintStrategy, self).__eq__(other))


class JvmCompile(NailgunTaskBase):
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

    register('--args', advanced=True, type=list,
             default=list(cls.get_args_default(register.bootstrap)), fingerprint=True,
             help='Pass these extra args to the compiler.')

    register('--confs', advanced=True, type=list, default=['default'],
             help='Compile for these Ivy confs.')

    # TODO: Stale analysis should be automatically ignored via Task identities:
    # https://github.com/pantsbuild/pants/issues/1351
    register('--clear-invalid-analysis', advanced=True, type=bool,
             help='When set, any invalid/incompatible analysis files will be deleted '
                  'automatically.  When unset, an error is raised instead.')

    register('--warnings', default=True, type=bool, fingerprint=True,
             help='Compile with all configured warnings enabled.')

    register('--warning-args', advanced=True, type=list, fingerprint=True,
             default=list(cls.get_warning_args_default()),
             help='Extra compiler args to use when warnings are enabled.')

    register('--no-warning-args', advanced=True, type=list, fingerprint=True,
             default=list(cls.get_no_warning_args_default()),
             help='Extra compiler args to use when warnings are disabled.')

    register('--fatal-warnings-enabled-args', advanced=True, type=list, fingerprint=True,
             default=list(cls.get_fatal_warnings_enabled_args_default()),
             help='Extra compiler args to use when fatal warnings are enabled.')

    register('--fatal-warnings-disabled-args', advanced=True, type=list, fingerprint=True,
             default=list(cls.get_fatal_warnings_disabled_args_default()),
             help='Extra compiler args to use when fatal warnings are disabled.')

    register('--debug-symbols', type=bool, fingerprint=True,
             help='Compile with debug symbol enabled.')

    register('--debug-symbol-args', advanced=True, type=list, fingerprint=True,
             default=['-C-g:lines,source,vars'],
             help='Extra args to enable debug symbol.')

    register('--delete-scratch', advanced=True, default=True, type=bool,
             help='Leave intermediate scratch files around, for debugging build problems.')

    register('--worker-count', advanced=True, type=int, default=cpu_count(),
             help='The number of concurrent workers to use when '
                  'compiling with {task}. Defaults to the '
                  'current machine\'s CPU count.'.format(task=cls._name))

    register('--size-estimator', advanced=True,
             choices=list(cls.size_estimators.keys()), default='filesize',
             help='The method of target size estimation. The size estimator estimates the size '
                  'of targets in order to build the largest targets first (subject to dependency '
                  'constraints). Choose \'random\' to choose random sizes for each target, which '
                  'may be useful for distributed builds.')

    register('--capture-log', advanced=True, type=bool,
             fingerprint=True,
             help='Capture compilation output to per-target logs.')

    register('--capture-classpath', advanced=True, type=bool, default=True,
             fingerprint=True,
             help='Capture classpath to per-target newline-delimited text files. These files will '
                  'be packaged into any jar artifacts that are created from the jvm targets.')

    register('--unused-deps', choices=['ignore', 'warn', 'fatal'], default='warn',
             fingerprint=True,
             help='Controls whether unused deps are checked, and whether they cause warnings or '
                  'errors.')

    register('--use-classpath-jars', advanced=True, type=bool, fingerprint=True,
             help='Use jar files on the compile_classpath. Note: Using this option degrades '
                  'incremental compile between targets.')

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
  _supports_concurrent_execution = None

  @classmethod
  def subsystem_dependencies(cls):
    return super(JvmCompile, cls).subsystem_dependencies() + (Java, JvmPlatform, ScalaPlatform)

  @classmethod
  def name(cls):
    return cls._name

  @classmethod
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

  @classmethod
  def get_fatal_warnings_enabled_args_default(cls):
    """Override to set default for --fatal-warnings-enabled-args option."""
    return ()

  @classmethod
  def get_fatal_warnings_disabled_args_default(cls):
    """Override to set default for --fatal-warnings-disabled-args option."""
    return ()

  @property
  def cache_target_dirs(self):
    return True

  def select(self, target):
    raise NotImplementedError()

  def select_source(self, source_file_path):
    raise NotImplementedError()

  def create_analysis_tools(self):
    """Returns an AnalysisTools implementation.

    Subclasses must implement.
    """
    raise NotImplementedError()

  def compile(self, args, classpath, sources, classes_output_dir, upstream_analysis, analysis_file,
              log_file, settings, fatal_warnings, javac_plugins_to_exclude):
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
    :param javac_plugins_to_exclude: A list of names of javac plugins that mustn't be used in
                                     this compilation, even if requested (typically because
                                     this compilation is building those same plugins).
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

    self._analysis_tools = self.create_analysis_tools()

    self._dep_context = DependencyContext(self.compiler_plugin_types(),
                                          dict(include_scopes=Scopes.JVM_COMPILE_SCOPES,
                                               respect_intransitive=True))

  @property
  def _unused_deps_check_enabled(self):
    return self.get_options().unused_deps != 'ignore'

  @memoized_property
  def _dep_analyzer(self):
    return JvmDependencyAnalyzer(get_buildroot(),
                                 self.context.products.get_data('runtime_classpath'),
                                 self.context.products.get_data('product_deps_by_src'))

  @property
  def _analysis_parser(self):
    return self._analysis_tools.parser

  def _fingerprint_strategy(self, classpath_products):
    return ResolvedJarAwareTaskIdentityFingerprintStrategy(self, classpath_products)

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

  def execute(self):
    # In case we have no relevant targets and return early create the requested product maps.
    self._create_empty_products()

    relevant_targets = list(self.context.targets(predicate=self.select))

    if not relevant_targets:
      return

    # Clone the compile_classpath to the runtime_classpath.
    compile_classpath = self.context.products.get_data('compile_classpath')
    classpath_product = self.context.products.get_data('runtime_classpath', compile_classpath.copy)

    def classpath_for_context(context):
      if self.get_options().use_classpath_jars:
        return context.jar_file
      return context.classes_dir

    fingerprint_strategy = self._fingerprint_strategy(classpath_product)
    # Note, JVM targets are validated (`vts.update()`) as they succeed.  As a result,
    # we begin writing artifacts out to the cache immediately instead of waiting for
    # all targets to finish.
    with self.invalidated(relevant_targets,
                          invalidate_dependents=True,
                          fingerprint_strategy=fingerprint_strategy,
                          topological_order=True) as invalidation_check:

      # Initialize the classpath for all targets.
      compile_contexts = {vt.target: self._compile_context(vt.target, vt.results_dir)
                          for vt in invalidation_check.all_vts}
      for cc in compile_contexts.values():
        classpath_product.add_for_target(cc.target, [(conf, classpath_for_context(cc))
                                                     for conf in self._confs])

      # Register products for valid targets.
      valid_targets = [vt.target for vt in invalidation_check.all_vts if vt.valid]
      self._register_vts([compile_contexts[t] for t in valid_targets])

      # Build any invalid targets (which will register products in the background).
      if invalidation_check.invalid_vts:
        self.do_compile(
          invalidation_check,
          compile_contexts,
          self.extra_compile_time_classpath_elements(),
        )

      if not self.get_options().use_classpath_jars:
        # Once compilation has completed, replace the classpath entry for each target with
        # its jar'd representation.
        for cc in compile_contexts.values():
          for conf in self._confs:
            classpath_product.remove_for_target(cc.target, [(conf, cc.classes_dir)])
            classpath_product.add_for_target(cc.target, [(conf, cc.jar_file)])

  def do_compile(self,
                 invalidation_check,
                 compile_contexts,
                 extra_compile_time_classpath_elements):
    """Executes compilations for the invalid targets contained in a single chunk."""

    invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]
    assert invalid_targets, "compile_chunk should only be invoked if there are invalid targets."

    # This ensures the workunit for the worker pool is set before attempting to compile.
    with self.context.new_workunit('isolation-{}-pool-bootstrap'.format(self._name)) \
            as workunit:
      # This uses workunit.parent as the WorkerPool's parent so that child workunits
      # of different pools will show up in order in the html output. This way the current running
      # workunit is on the bottom of the page rather than possibly in the middle.
      worker_pool = WorkerPool(workunit.parent,
                               self.context.run_tracker,
                               self._worker_count)


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
                                     invalidation_check.invalid_vts)

    exec_graph = ExecutionGraph(jobs)
    try:
      exec_graph.execute(worker_pool, self.context.log)
    except ExecutionFailure as e:
      raise TaskError("Compilation failure: {}".format(e))

  def _record_compile_classpath(self, classpath, targets, outdir):
    text = '\n'.join(classpath)
    for target in targets:
      path = os.path.join(outdir, 'compile_classpath', '{}.txt'.format(target.id))
      safe_mkdir(os.path.dirname(path), clean=False)
      with open(path, 'w') as f:
        f.write(text.encode('utf-8'))

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
        if self.get_options().capture_classpath:
          self._record_compile_classpath(classpath, vts.targets, outdir)

        # If compiling a plugin, don't try to use it on itself.
        javac_plugins_to_exclude = (t.plugin for t in vts.targets if isinstance(t, JavacPlugin))
        self.compile(self._args, classpath, sources, outdir, upstream_analysis, analysis_file,
                     log_file, settings, fatal_warnings, javac_plugins_to_exclude)

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

    if self.context.products.is_required_data('product_deps_by_src') \
        or self._unused_deps_check_enabled:
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

    # Register a mapping between sources and classfiles (if requested).
    if classes_by_source is not None:
      ccbsbc = self.compute_classes_by_source(compile_contexts).items()
      for compile_context, computed_classes_by_source in ccbsbc:
        classes_dir = compile_context.classes_dir

        for source in compile_context.sources:
          classes = computed_classes_by_source.get(source, [])
          classes_by_source[source].add_abs_paths(classes_dir, classes)

    # Register classfile product dependencies (if requested).
    if product_deps_by_src is not None:
      for compile_context in compile_contexts:
        product_deps_by_src[compile_context.target] = \
            self._analysis_parser.parse_deps_from_path(compile_context.analysis_file)

  def _check_unused_deps(self, compile_context):
    """Uses `product_deps_by_src` to check unused deps and warn or error."""
    with self.context.new_workunit('unused-check', labels=[WorkUnitLabel.COMPILER]):
      # Compute replacement deps.
      replacement_deps = self._dep_analyzer.compute_unused_deps(compile_context.target)

      if not replacement_deps:
        return

      # Warn or error for unused.
      def joined_dep_msg(deps):
        return '\n  '.join('\'{}\','.format(dep.address.spec) for dep in sorted(deps))
      flat_replacements = set(r for replacements in replacement_deps.values() for r in replacements)
      replacements_msg = ''
      if flat_replacements:
        replacements_msg = 'Suggested replacements:\n  {}\n'.format(joined_dep_msg(flat_replacements))
      unused_msg = (
          'unused dependencies:\n  {}\n{}'
          '(If you\'re seeing this message in error, you might need to '
          'change the `scope` of the dependencies.)'.format(
            joined_dep_msg(replacement_deps.keys()),
            replacements_msg,
          )
        )
      if self.get_options().unused_deps == 'fatal':
        raise TaskError(unused_msg)
      else:
        self.context.log.warn('Target {} had {}\n'.format(
          compile_context.target.address.spec, unused_msg))

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
                           invalid_targets, invalid_vts):
    class Counter(object):
      def __init__(self, size, initial=0):
        self.size = size
        self.count = initial

      def __call__(self):
        self.count += 1
        return self.count

      def format_length(self):
        return len(str(self.size))
    counter = Counter(len(invalid_vts))

    def check_cache(vts):
      """Manually checks the artifact cache (usually immediately before compilation.)

      Returns true if the cache was hit successfully, indicating that no compilation is necessary.
      """
      if not self.artifact_cache_reads_enabled():
        return False
      cached_vts, _, _ = self.check_artifact_cache([vts])
      if not cached_vts:
        self.context.log.debug('Missed cache during double check for {}'
                               .format(vts.target.address.spec))
        return False
      assert cached_vts == [vts], (
          'Cache returned unexpected target: {} vs {}'.format(cached_vts, [vts])
      )
      self.context.log.info('Hit cache during double check for {}'.format(vts.target.address.spec))
      counter()
      return True

    def should_compile_incrementally(vts, ctx):
      """Check to see if the compile should try to re-use the existing analysis.

      Returns true if we should try to compile the target incrementally.
      """
      if not vts.is_incremental:
        return False
      if not self._clear_invalid_analysis:
        return True
      return os.path.exists(ctx.analysis_file)

    def work_for_vts(vts, ctx):
      progress_message = ctx.target.address.spec

      # Capture a compilation log if requested.
      log_file = ctx.log_file if self._capture_log else None

      # Double check the cache before beginning compilation
      hit_cache = check_cache(vts)

      if not hit_cache:
        # Compute the compile classpath for this target.
        cp_entries = [ctx.classes_dir]
        cp_entries.extend(ClasspathUtil.compute_classpath(ctx.dependencies(self._dep_context),
                                                          classpath_products,
                                                          extra_compile_time_classpath,
                                                          self._confs))
        upstream_analysis = dict(self._upstream_analysis(compile_contexts, cp_entries))

        if not should_compile_incrementally(vts, ctx):
          # Purge existing analysis file in non-incremental mode.
          safe_delete(ctx.analysis_file)
          # Work around https://github.com/pantsbuild/pants/issues/3670
          safe_rmtree(ctx.classes_dir)

        tgt, = vts.targets
        fatal_warnings = self._compute_language_property(tgt, lambda x: x.fatal_warnings)
        self._compile_vts(vts,
                          ctx.sources,
                          ctx.analysis_file,
                          upstream_analysis,
                          cp_entries,
                          ctx.classes_dir,
                          log_file,
                          progress_message,
                          tgt.platform,
                          fatal_warnings,
                          counter)
        self._analysis_tools.relativize(ctx.analysis_file, ctx.portable_analysis_file)

        # Write any additional resources for this target to the target workdir.
        self.write_extra_resources(ctx)

        # Jar the compiled output.
        self._create_context_jar(ctx)

      # Update the products with the latest classes.
      self._register_vts([ctx])

      # Once products are registered, check for unused dependencies (if enabled).
      if not hit_cache and self._unused_deps_check_enabled:
        self._check_unused_deps(ctx)

    jobs = []
    invalid_target_set = set(invalid_targets)
    for ivts in invalid_vts:
      # Invalidated targets are a subset of relevant targets: get the context for this one.
      compile_target = ivts.target
      compile_context = compile_contexts[compile_target]
      invalid_dependencies = self._collect_invalid_compile_dependencies(compile_target,
                                                                        invalid_target_set)

      jobs.append(Job(self.exec_graph_key_for_target(compile_target),
                      functools.partial(work_for_vts, ivts, compile_context),
                      [self.exec_graph_key_for_target(target) for target in invalid_dependencies],
                      self._size_estimator(compile_context.sources),
                      # If compilation and analysis work succeeds, validate the vts.
                      # Otherwise, fail it.
                      on_success=ivts.update,
                      on_failure=ivts.force_invalidate))
    return jobs

  def _collect_invalid_compile_dependencies(self, compile_target, invalid_target_set):
    # Collects all invalid dependencies that are not dependencies of other invalid dependencies
    # within the closure of compile_target.
    invalid_dependencies = OrderedSet()

    def work(target):
      pass

    def predicate(target):
      if target is compile_target:
        return True
      if target in invalid_target_set:
        invalid_dependencies.add(target)
        return False
      return True

    compile_target.walk(work, predicate)
    return invalid_dependencies

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
      for tgt in target_sources:
        if tgt.has_sources():
          resolved_sources.extend(tgt.sources_relative_to_buildroot())
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

    prop = False
    if target.has_sources('.java'):
      prop |= selector(Java.global_instance())
    if target.has_sources('.scala'):
      prop |= selector(ScalaPlatform.global_instance())
    return prop

  def _compute_extra_classpath(self, extra_compile_time_classpath_elements):
    """Compute any extra compile-time-only classpath elements.

    TODO(benjy): Model compile-time vs. runtime classpaths more explicitly.
    """
    def extra_compile_classpath_iter():
      for conf in self._confs:
        for jar in extra_compile_time_classpath_elements:
          yield (conf, jar)

    return list(extra_compile_classpath_iter())
