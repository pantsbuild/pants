# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import sys
from collections import defaultdict

from pants.backend.core.tasks.group_task import GroupMember
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.tasks.jvm_compile.jvm_compile_global_strategy import JvmCompileGlobalStrategy
from pants.backend.jvm.tasks.jvm_compile.jvm_compile_isolated_strategy import \
  JvmCompileIsolatedStrategy
from pants.backend.jvm.tasks.nailgun_task import NailgunTaskBase
from pants.base.fingerprint_strategy import TaskIdentityFingerprintStrategy
from pants.base.workunit import WorkUnitLabel
from pants.goal.products import MultipleRootedProducts
from pants.option.custom_types import list_option
from pants.reporting.reporting_utils import items_to_report_element


class JvmCompile(NailgunTaskBase, GroupMember):
  """A common framework for JVM compilation.

  To subclass for a specific JVM language, implement the static values and methods
  mentioned below under "Subclasses must implement".
  """

  @classmethod
  def register_options(cls, register):
    super(JvmCompile, cls).register_options(register)
    register('--partition-size-hint', advanced=True, type=int, default=sys.maxint,
             metavar='<# source files>',
             help='Roughly how many source files to attempt to compile together. Set to a large '
                  'number to compile all sources together. Set to 0 to compile target-by-target.')

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

    register('--strategy', advanced=True, choices=['global', 'isolated'], default='global',
             fingerprint=True,
             help='Selects the compilation strategy to use. The "global" strategy uses a shared '
                  'global classpath for all compiled classes, and the "isolated" strategy uses '
                  'per-target classpaths.')

    register('--delete-scratch', advanced=True, default=True, action='store_true',
             help='Leave intermediate scratch files around, for debugging build problems.')

    JvmCompileGlobalStrategy.register_options(register, cls._name, cls._supports_concurrent_execution)
    JvmCompileIsolatedStrategy.register_options(register, cls._name, cls._supports_concurrent_execution)

  @classmethod
  def product_types(cls):
    raise TaskError('Expected to be installed in GroupTask, which has its own '
                    'product_types implementation.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(JvmCompile, cls).prepare(options, round_manager)

    round_manager.require_data('compile_classpath')
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
    """Source predicate for the strategy."""
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

    # The compile strategy to use for analysis and classfile placement.
    if self.get_options().strategy == 'global':
      strategy_constructor = JvmCompileGlobalStrategy
    else:
      assert self.get_options().strategy == 'isolated'
      strategy_constructor = JvmCompileIsolatedStrategy
    self._strategy = strategy_constructor(self.context,
                                          self.get_options(),
                                          self.workdir,
                                          self.create_analysis_tools(),
                                          self._name,
                                          self.select_source)
    # Maps CompileContext --> dict of upstream class to paths.
    self._upstream_class_to_paths = {}

  def _fingerprint_strategy(self):
    return TaskIdentityFingerprintStrategy(self)

  def pre_execute(self):
    # Only create these working dirs during execution phase, otherwise, they
    # would be wiped out by clean-all goal/task if it's specified.
    self._strategy.pre_compile()

    # TODO(John Sirois): Ensuring requested product maps are available - if empty - should probably
    # be lifted to Task infra.

    # In case we have no relevant targets and return early create the requested product maps.
    self._create_empty_products()

  def prepare_execute(self, chunks):
    targets_in_chunks = list(itertools.chain(*chunks))

    # Invoke the strategy's prepare_compile to prune analysis.
    cache_manager = self.create_cache_manager(invalidate_dependents=True,
                                              fingerprint_strategy=self._fingerprint_strategy())
    self._strategy.prepare_compile(cache_manager, self.context.targets(), targets_in_chunks)

  def execute_chunk(self, relevant_targets):
    if not relevant_targets:
      return
    # Invalidation check. Everything inside the with block must succeed for the
    # invalid targets to become valid.
    partition_size_hint, locally_changed_targets = self._strategy.invalidation_hints(relevant_targets)
    with self.invalidated(relevant_targets,
                          invalidate_dependents=True,
                          partition_size_hint=partition_size_hint,
                          locally_changed_targets=locally_changed_targets,
                          fingerprint_strategy=self._fingerprint_strategy(),
                          topological_order=True) as invalidation_check:
      if invalidation_check.invalid_vts:
        # Find the invalid targets for this chunk.
        invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]

        # Register products for all the valid targets.
        # We register as we go, so dependency checking code can use this data.
        valid_targets = list(set(relevant_targets) - set(invalid_targets))
        valid_compile_contexts = [self._strategy.compile_context(t) for t in valid_targets]
        self._register_vts(valid_compile_contexts)

        # Invoke the strategy to execute compilations for invalid targets.
        update_artifact_cache_vts_work = (self.get_update_artifact_cache_work
            if self.artifact_cache_writes_enabled() else None)
        self._strategy.compile_chunk(invalidation_check,
                                     self.context.targets(),
                                     relevant_targets,
                                     invalid_targets,
                                     self.extra_compile_time_classpath_elements(),
                                     self._compile_vts,
                                     self._register_vts,
                                     update_artifact_cache_vts_work)
      else:
        # Nothing to build. Register products for all the targets in one go.
        self._register_vts([self._strategy.compile_context(t) for t in relevant_targets])

  def finalize_execute(self, chunks):
    targets_in_chunks = list(itertools.chain(*chunks))
    self._strategy.finalize_compile(targets_in_chunks)

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
    post_process_cached_vts = lambda cvts: self._strategy.post_process_cached_vts(cvts)
    return self.do_check_artifact_cache(vts, post_process_cached_vts=post_process_cached_vts)

  def _create_empty_products(self):
    make_products = lambda: defaultdict(MultipleRootedProducts)
    if self.context.products.is_required_data('classes_by_source'):
      self.context.products.safe_create_data('classes_by_source', make_products)

    # Whether or not anything else requires resources_by_target, this task
    # uses it internally.
    self.context.products.safe_create_data('resources_by_target', make_products)

    # JvmDependencyCheck uses classes_by_target
    self.context.products.safe_create_data('classes_by_target', make_products)

    self.context.products.safe_create_data('actual_source_deps', dict)

  def _register_vts(self, compile_contexts):
    classes_by_source = self.context.products.get_data('classes_by_source')
    classes_by_target = self.context.products.get_data('classes_by_target')
    compile_classpath = self.context.products.get_data('compile_classpath')
    resources_by_target = self.context.products.get_data('resources_by_target')
    actual_source_deps = self.context.products.get_data('actual_source_deps')

    # Register class products (and resources generated by annotation processors.)
    computed_classes_by_source_by_context = self._strategy.compute_classes_by_source(
        compile_contexts)
    resource_mapping = self._strategy.compute_resource_mapping(compile_contexts)
    for compile_context in compile_contexts:
      computed_classes_by_source = computed_classes_by_source_by_context[compile_context]
      target = compile_context.target
      classes_dir = compile_context.classes_dir

      def add_products_by_target(files):
        for f in files:
          clsname = self._strategy.class_name_for_class_file(compile_context, f)
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

    # Register resource products.
    for compile_context in compile_contexts:
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

      classpath = [path for (conf, path) in entries if conf in self._confs]
      dep_map = self._strategy.parse_deps(classpath, compile_context)

      def normalize(dep):
        if dep.endswith('.class'):
          # Normalize the class path to class names
          return self._strategy.class_name_for_class_file(compile_context, dep)
        else:
          return dep

      actual_source_deps[compile_context.target] = {
          f: [normalize(d) for d in dep_map[f]]
          for f in dep_map
        }
