# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import sys
from collections import defaultdict

from pants.backend.core.tasks.group_task import GroupMember
from pants.backend.jvm.tasks.jvm_compile.jvm_compile_global_strategy import JvmCompileGlobalStrategy
from pants.backend.jvm.tasks.jvm_compile.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.backend.jvm.tasks.jvm_compile.jvm_fingerprint_strategy import JvmFingerprintStrategy
from pants.backend.jvm.tasks.nailgun_task import NailgunTaskBase
from pants.goal.products import MultipleRootedProducts
from pants.option.options import Options
from pants.reporting.reporting_utils import items_to_report_element


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

  def compile(self, args, classpath, sources, classes_output_dir, upstream_analysis, analysis_file):
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

  def post_process(self, all_targets, relevant_targets):
    """Any extra post-execute work."""
    pass

  def __init__(self, *args, **kwargs):
    super(JvmCompile, self).__init__(*args, **kwargs)

    # JVM options for running the compiler.
    self._jvm_options = self.get_options().jvm_options

    self._args = list(self.get_options().args)
    if self.get_options().warnings:
      self._args.extend(self.get_options().warning_args)
    else:
      self._args.extend(self.get_options().no_warning_args)

    self.setup_artifact_cache()

    # The ivy confs for which we're building.
    self._confs = self.get_options().confs

    # The compile strategy to use for analysis and classfile placement.
    self._strategy = JvmCompileGlobalStrategy(self.context,
                                              self.get_options(),
                                              self.workdir,
                                              self.create_analysis_tools(),
                                              lambda s: s.endswith(self._file_suffix))

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
    self._strategy.pre_compile()

    # TODO(John Sirois): Ensuring requested product maps are available - if empty - should probably
    # be lifted to Task infra.

    # In case we have no relevant targets and return early create the requested product maps.
    self._create_empty_products()

  def prepare_execute(self, chunks):
    targets_in_chunk = list(itertools.chain(*chunks))

    # Invoke the strategy's prepare_compile to prune analysis.
    cache_manager = self.create_cache_manager(invalidate_dependents=True,
                                              fingerprint_strategy=self._jvm_fingerprint_strategy())
    self._strategy.prepare_compile(cache_manager, self.context.targets(), targets_in_chunk)

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
                          fingerprint_strategy=self._jvm_fingerprint_strategy(),
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

    self.post_process(self.context.targets(), relevant_targets)

  def _compile_vts(self, vts, sources, analysis_file, upstream_analysis, classpath, outdir, progress_message):
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
      self.context.log.warn('Skipping %s compile for targets with no sources:\n  %s'
                            % (self.name(), vts.targets))
    else:
      # Do some reporting.
      self.context.log.info(
        'Compiling ',
        items_to_report_element(sources, '%s source' % self.name()),
        ' in ',
        items_to_report_element([t.address.reference() for t in vts.targets], 'target'),
        ' (',
        progress_message,
        ').')
      with self.context.new_workunit('compile'):
        # The compiler may delete classfiles, then later exit on a compilation error. Then if the
        # change triggering the error is reverted, we won't rebuild to restore the missing
        # classfiles. So we force-invalidate here, to be on the safe side.
        vts.force_invalidate()
        self.compile(self._args, classpath, sources, outdir, upstream_analysis, analysis_file)

  def check_artifact_cache(self, vts):
    post_process_cached_vts = lambda vts: self._strategy.post_process_cached_vts(vts)
    return self.do_check_artifact_cache(vts, post_process_cached_vts=post_process_cached_vts)


  def _create_empty_products(self):
    make_products = lambda: defaultdict(MultipleRootedProducts)
    if self.context.products.is_required_data('classes_by_source'):
      self.context.products.safe_create_data('classes_by_source', make_products)

    # Whether or not anything else requires resources_by_target, this task
    # uses it internally.
    self.context.products.safe_create_data('resources_by_target', make_products)

    # JvmDependencyAnalyzer uses classes_by_target within this run
    self.context.products.safe_create_data('classes_by_target', make_products)

  def _register_vts(self, compile_contexts):
    classes_by_source = self.context.products.get_data('classes_by_source')
    classes_by_target = self.context.products.get_data('classes_by_target')
    resources_by_target = self.context.products.get_data('resources_by_target')

    if classes_by_source is not None or classes_by_target is not None:
      computed_classes_by_source = self._strategy.compute_classes_by_source(compile_contexts)
      resource_mapping = self._strategy.compute_resource_mapping(compile_contexts)
      for compile_context in compile_contexts:
        target = compile_context.target
        classes_dir = compile_context.classes_dir
        target_products = classes_by_target[target] if classes_by_target is not None else None
        for source in compile_context.sources:  # Sources are relative to buildroot.
          classes = computed_classes_by_source.get(source, [])  # Classes are absolute paths.
          for cls in classes:
            clsname = self._strategy.class_name_for_class_file(compile_context, cls)
            resources = resource_mapping.get(clsname, [])
            resources_by_target[target].add_abs_paths(classes_dir, resources)

          if classes_by_target is not None:
            target_products.add_abs_paths(classes_dir, classes)
          if classes_by_source is not None:
            classes_by_source[source].add_abs_paths(classes_dir, classes)

    # TODO(pl): https://github.com/pantsbuild/pants/issues/206
    if resources_by_target is not None:
      for compile_context in compile_contexts:
        target_resources = resources_by_target[compile_context.target]
        for root, abs_paths in self.extra_products(compile_context.target):
          target_resources.add_abs_paths(root, abs_paths)
