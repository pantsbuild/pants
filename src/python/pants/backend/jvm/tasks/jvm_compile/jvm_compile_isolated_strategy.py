# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import uuid
from collections import OrderedDict, defaultdict
from contextlib import contextmanager

from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.jvm_compile.execution_graph import (ExecutionFailure, ExecutionGraph,
                                                                 Job)
from pants.backend.jvm.tasks.jvm_compile.jvm_compile_strategy import JvmCompileStrategy
from pants.backend.jvm.tasks.jvm_compile.resource_mapping import ResourceMapping
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.worker_pool import Work, WorkerPool
from pants.util.dirutil import safe_delete, safe_mkdir, safe_walk
from pants.util.memo import memoized_property


class JvmCompileIsolatedStrategy(JvmCompileStrategy):
  """A strategy for JVM compilation that uses per-target classpaths and analysis."""

  @classmethod
  def register_options(cls, register, language, supports_concurrent_execution):
    if supports_concurrent_execution:
      register('--worker-count', type=int, default=1, advanced=True,
               help='The number of concurrent workers to use compiling {lang} sources with the isolated'
                    ' strategy. This is a beta feature.'.format(lang=language))

  def __init__(self, context, options, workdir, analysis_tools, language, sources_predicate):
    super(JvmCompileIsolatedStrategy, self).__init__(context, options, workdir, analysis_tools,
                                                     language, sources_predicate)

    # Various working directories.
    self._analysis_dir = os.path.join(workdir, 'isolated-analysis')
    self._classes_dir = os.path.join(workdir, 'isolated-classes')

    try:
      worker_count = options.worker_count
    except AttributeError:
      # tasks that don't support concurrent execution have no worker_count registered
      worker_count = 1

    self._worker_count = worker_count
    self._worker_pool = None

  def name(self):
    return 'isolated'

  def compile_context(self, target):
    analysis_file = JvmCompileStrategy._analysis_for_target(self._analysis_dir, target)
    classes_dir = os.path.join(self._classes_dir, target.id)
    return self.CompileContext(target,
                               analysis_file,
                               classes_dir,
                               self._sources_for_target(target))

  def _create_compile_contexts_for_targets(self, targets):
    compile_contexts = OrderedDict()
    for target in targets:
      compile_context = self.compile_context(target)
      compile_contexts[target] = compile_context
    return compile_contexts

  def pre_compile(self):
    super(JvmCompileIsolatedStrategy, self).pre_compile()
    safe_mkdir(self._analysis_dir)
    safe_mkdir(self._classes_dir)
    self.ensure_analysis_tmpdir()


  def prepare_compile(self, cache_manager, all_targets, relevant_targets):
    super(JvmCompileIsolatedStrategy, self).prepare_compile(cache_manager, all_targets,
                                                            relevant_targets)

    # TODO: Look for invalid analysis files like in Global's pre_compile() ?

    # Update the classpath by adding relevant target's classes directories to its classpath.
    compile_classpaths = self.context.products.get_data('compile_classpath')

    with self.context.new_workunit('validate-{}-analysis'.format(self._language)):
      for target in relevant_targets:
        cc = self.compile_context(target)
        safe_mkdir(cc.classes_dir)
        compile_classpaths.add_for_target(target, [(conf, cc.classes_dir) for conf in self._confs])
        self.validate_analysis(cc.analysis_file)

    # This ensures the workunit for the worker pool is set
    with self.context.new_workunit('isolation-{}-pool-bootstrap'.format(self._language)) \
            as workunit:
      # This uses workunit.parent as the WorkerPool's parent so that child workunits
      # of different pools will show up in order in the html output. This way the current running
      # workunit is on the bottom of the page rather than possibly in the middle.
      self._worker_pool = WorkerPool(workunit.parent,
                                     self.context.run_tracker,
                                     self._worker_count)

  def invalidation_hints(self, relevant_targets):
    # No partitioning.
    return (0, None)

  def compute_classes_by_source(self, compile_contexts):
    buildroot = get_buildroot()
    classes_by_src_by_context = defaultdict(dict)
    for compile_context in compile_contexts:
      if not os.path.exists(compile_context.analysis_file):
        continue
      products = self._analysis_parser.parse_products_from_path(compile_context.analysis_file,
                                                                compile_context.classes_dir)
      classes_by_src = classes_by_src_by_context[compile_context]
      for src, classes in products.items():
        relsrc = os.path.relpath(src, buildroot)
        classes_by_src[relsrc] = classes
    return classes_by_src_by_context

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

  def exec_graph_key_for_target(self, compile_target):
    return "compile-{}".format(compile_target.address.spec)

  @contextmanager
  def _empty_analysis_cleanup(self, compile_context):
    """Addresses cases where failed compilations leave behind invalid analysis.

    If compilation was creating analysis for the first time, and it fails, then the analysis
    will be empty/invalid.
    """
    preexisting_analysis = os.path.exists(compile_context.analysis_file)
    try:
      yield
    except:
      if not preexisting_analysis:
        safe_delete(compile_context.analysis_file)
      raise

  def _create_compile_jobs(self, compile_classpaths,
                           compile_contexts, extra_compile_time_classpath,
                     invalid_targets, invalid_vts_partitioned,  compile_vts, register_vts,
                     update_artifact_cache_vts_work):
    def create_work_for_vts(vts, compile_context, target_closure):
      def work():
        progress_message = vts.targets[0].address.spec
        cp_entries = self._compute_classpath_entries(compile_classpaths,
                                                     target_closure,
                                                     compile_context,
                                                     extra_compile_time_classpath)

        upstream_analysis = dict(self._upstream_analysis(compile_contexts, cp_entries))

        tmpdir = os.path.join(self.analysis_tmpdir, str(uuid.uuid4()))
        safe_mkdir(tmpdir)

        with self._empty_analysis_cleanup(compile_context):
          tmp_analysis_file = JvmCompileStrategy._analysis_for_target(
              tmpdir, compile_context.target)
          if os.path.exists(compile_context.analysis_file):
            shutil.copy(compile_context.analysis_file, tmp_analysis_file)
          compile_vts(vts,
                      compile_context.sources,
                      tmp_analysis_file,
                      upstream_analysis,
                      cp_entries,
                      compile_context.classes_dir,
                      progress_message)
          shutil.copy(tmp_analysis_file, compile_context.analysis_file)

        # Update the products with the latest classes.
        register_vts([compile_context])

        # Kick off the background artifact cache write.
        if update_artifact_cache_vts_work:
          self._write_to_artifact_cache(vts, compile_context, update_artifact_cache_vts_work)

      return work

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
                      create_work_for_vts(vts, compile_context, compile_target_closure),
                      [self.exec_graph_key_for_target(target) for target in invalid_dependencies],
                      # If compilation and analysis work succeeds, validate the vts.
                      # Otherwise, fail it.
                      on_success=vts.update,
                      on_failure=vts.force_invalidate))
    return jobs

  def compile_chunk(self,
                    invalidation_check,
                    all_targets,
                    relevant_targets,
                    invalid_targets,
                    extra_compile_time_classpath_elements,
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
                                     compile_vts,
                                     register_vts,
                                     update_artifact_cache_vts_work)


    exec_graph = ExecutionGraph(jobs)
    try:
      exec_graph.execute(self._worker_pool, self.context.log)
    except ExecutionFailure as e:
      raise TaskError("Compilation failure: {}".format(e))

  def compute_resource_mapping(self, compile_contexts):
    return ResourceMapping(self._classes_dir)

  def post_process_cached_vts(self, cached_vts):
    """Localizes the fetched analysis for targets we found in the cache.

    This is the complement of `_write_to_artifact_cache`.
    """
    compile_contexts = []
    for vt in cached_vts:
      for target in vt.targets:
        compile_contexts.append(self.compile_context(target))

    for compile_context in compile_contexts:
      portable_analysis_file = JvmCompileStrategy._portable_analysis_for_target(
          self._analysis_dir, compile_context.target)
      if os.path.exists(portable_analysis_file):
        self._analysis_tools.localize(portable_analysis_file, compile_context.analysis_file)

  def _write_to_artifact_cache(self, vts, compile_context, get_update_artifact_cache_work):
    assert len(vts.targets) == 1
    assert vts.targets[0] == compile_context.target

    # Noop if the target is uncacheable.
    if (compile_context.target.has_label('no_cache')):
      return
    vt = vts.versioned_targets[0]

    # Set up args to relativize analysis in the background.
    # TODO: GlobalStrategy puts portable analysis in a tmp directory... shall we?
    portable_analysis_file = JvmCompileStrategy._portable_analysis_for_target(
        self._analysis_dir, compile_context.target)
    relativize_args_tuple = (compile_context.analysis_file, portable_analysis_file)

    # Compute the classes and resources for this target.
    artifacts = []
    resources_by_target = self.context.products.get_data('resources_by_target')
    if resources_by_target is not None:
      for _, paths in resources_by_target[compile_context.target].abs_paths():
        artifacts.extend(paths)
    for dirpath, _, filenames in safe_walk(compile_context.classes_dir):
      artifacts.extend([os.path.join(dirpath, f) for f in filenames])

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

  @memoized_property
  def analysis_tmpdir(self):
    """A temporary, but well-known, dir in which to munge analysis/dependency files in before
    caching. It must be well-known so we know where to find the files when we retrieve them from
    the cache.
    :return:
    """
    return os.path.join(self._analysis_dir, 'artifact_cache_tmpdir')
