# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import logging
import os
import re

from pants.backend.jvm.subsystems.dependency_context import DependencyContext  # noqa
from pants.backend.jvm.subsystems.rsc import Rsc
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_entry import ClasspathEntry
from pants.backend.jvm.tasks.jvm_compile.compile_context import CompileContext
from pants.backend.jvm.tasks.jvm_compile.execution_graph import Job
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.mirrored_target_option_mixin import MirroredTargetOptionMixin
from pants.engine.fs import (EMPTY_DIRECTORY_DIGEST, DirectoryToMaterialize, PathGlobs,
                             PathGlobsAndRoot)
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.java.jar.jar_dependency import JarDependency
from pants.reporting.reporting_utils import items_to_report_element
from pants.util.collections import assert_single_element
from pants.util.contextutil import Timer
from pants.util.dirutil import fast_relpath, fast_relpath_optional, safe_mkdir
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import datatype, enum
from pants.util.strutil import safe_shlex_join


#
# This is a subclass of zinc compile that uses both Rsc and Zinc to do
# compilation.
# It uses Rsc and the associated tools to outline scala targets. It then
# passes those outlines to zinc to produce the final compile artifacts.
#
#
logger = logging.getLogger(__name__)


def fast_relpath_collection(collection):
  buildroot = get_buildroot()
  return [fast_relpath_optional(c, buildroot) or c for c in collection]


def stdout_contents(wu):
  if isinstance(wu, FallibleExecuteProcessResult):
    return wu.stdout.rstrip()
  with open(wu.output_paths()['stdout']) as f:
    return f.read().rstrip()


def _create_desandboxify_fn(possible_path_patterns):
  # Takes a collection of possible canonical prefixes, and returns a function that
  # if it finds a matching prefix, strips the path prior to the prefix and returns it
  # if it doesn't it returns the original path
  # TODO remove this after https://github.com/scalameta/scalameta/issues/1791 is released
  regexes = [re.compile('/({})'.format(p)) for p in possible_path_patterns]
  def desandboxify(path):
    if not path:
      return path
    for r in regexes:
      match = r.search(path)
      if match:
        logger.debug('path-cleanup: matched {} with {} against {}'.format(match, r.pattern, path))
        return match.group(1)
    logger.debug('path-cleanup: no match for {}'.format(path))
    return path
  return desandboxify


class CompositeProductAdder:
  def __init__(self, *products):
    self.products = products

  def add_for_target(self, *args, **kwargs):
    for product in self.products:
      product.add_for_target(*args, **kwargs)


class RscCompileContext(CompileContext):
  def __init__(self,
               target,
               analysis_file,
               classes_dir,
               rsc_jar_file,
               jar_file,
               log_dir,
               args_file,
               post_compile_merge_dir,
               sources,
               workflow):
    super().__init__(target, analysis_file, classes_dir, jar_file, log_dir, args_file, post_compile_merge_dir, sources)
    self.workflow = workflow
    self.rsc_jar_file = rsc_jar_file

  def ensure_output_dirs_exist(self):
    safe_mkdir(os.path.dirname(self.rsc_jar_file.path))


class RscCompile(ZincCompile, MirroredTargetOptionMixin):
  """Compile Scala and Java code to classfiles using Rsc."""

  _name = 'mixed' # noqa
  compiler_name = 'rsc'

  @memoized_property
  def mirrored_target_option_actions(self):
    return {
      'workflow': self._identify_workflow_tags,
    }

  @classmethod
  def implementation_version(cls):
    return super().implementation_version() + [('RscCompile', 173)]

  class JvmCompileWorkflowType(enum(['zinc-only', 'zinc-java', 'rsc-and-zinc'])):
    """Target classifications used to correctly schedule Zinc and Rsc jobs.

    There are some limitations we have to work around before we can compile everything through Rsc
    and followed by Zinc.
    - rsc is not able to outline all scala code just yet (this is also being addressed through
      automated rewrites).
    - javac is unable to consume rsc's jars just yet.
    - rsc is not able to outline all java code just yet (this is likely to *not* require rewrites,
      just some more work on rsc).

    As we work on improving our Rsc integration, we'll need to create more workflows to more closely
    map the supported features of Rsc. This enum class allows us to do that.

      - zinc-only: compiles targets just with Zinc and uses the Zinc products of their dependencies.
      - zinc-java: the same as zinc-only for now, for targets with any java sources (which rsc can't
                   syet outline).
      - rsc-and-zinc: compiles targets with Rsc to create "header" jars, and runs Zinc against the
        Rsc products of their dependencies. The Rsc compile uses the Rsc products of Rsc compatible
        targets and the Zinc products of zinc-only targets.
    """

  @memoized_property
  def _compiler_tags(self):
    return {
      '{prefix}:{workflow_name}'.format(
        prefix=self.get_options().force_compiler_tag_prefix,
        workflow_name=workflow.value): workflow
      for workflow in self.JvmCompileWorkflowType.all_variants
    }

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--force-compiler-tag-prefix', default='use-compiler', metavar='<tag>',
      help='Always compile targets marked with this tag with rsc, unless the workflow is '
           'specified on the cli.')
    register('--workflow', type=cls.JvmCompileWorkflowType,
      default=cls.JvmCompileWorkflowType.zinc_only, metavar='<workflow>',
      help='The workflow to use to compile JVM targets.', fingerprint=True)

    register('--extra-rsc-args', type=list, default=[],
             help='Extra arguments to pass to the rsc invocation.')

    cls.register_jvm_tool(
      register,
      'rsc',
      classpath=[
        JarDependency(
          org='com.twitter',
          name='rsc_2.12',
          rev='0.0.0-768-7357aa0a',
        ),
      ],
      custom_rules=[
        Shader.exclude_package('rsc', recursive=True),
      ]
    )

  @classmethod
  def product_types(cls):
    return super(RscCompile, cls).product_types() + ['rsc_mixed_compile_classpath']

  @memoized_property
  def _rsc(self):
    return Rsc.global_instance()

  @memoized_property
  def _rsc_classpath(self):
    return self.tool_classpath('rsc')

  # TODO: allow @memoized_method to convert lists into tuples so they can be hashed!
  @memoized_property
  def _nailgunnable_combined_classpath(self):
    """Register all of the component tools of the rsc compile task as a "combined" jvm tool.

    This allows us to invoke their combined classpath in a single nailgun instance (see #7089 and
    #7092). We still invoke their classpaths separately when not using nailgun, however.
    """
    cp = []
    cp.extend(self._rsc_classpath)
    # Add zinc's classpath so that it can be invoked from the same nailgun instance.
    cp.extend(super().get_zinc_compiler_classpath())
    return cp

  # Overrides the normal zinc compiler classpath, which only contains zinc.
  def get_zinc_compiler_classpath(self):
    return self.execution_strategy_enum.resolve_for_enum_variant({
      # NB: We must use the verbose version of super() here, possibly because of the lambda.
      self.HERMETIC: lambda: super(RscCompile, self).get_zinc_compiler_classpath(),
      self.SUBPROCESS: lambda: super(RscCompile, self).get_zinc_compiler_classpath(),
      self.NAILGUN: lambda: self._nailgunnable_combined_classpath,
    })()

  def register_extra_products_from_contexts(self, targets, compile_contexts):
    super().register_extra_products_from_contexts(targets, compile_contexts)

    def confify(entries):
      return [(conf, e) for e in entries for conf in self._confs]

    # Ensure that the jar/rsc jar is on the rsc_mixed_compile_classpath.
    for target in targets:
      merged_cc = compile_contexts[target]
      rsc_cc = merged_cc.rsc_cc
      zinc_cc = merged_cc.zinc_cc
      if rsc_cc.workflow is not None:
        cp_entries = rsc_cc.workflow.resolve_for_enum_variant({
          'zinc-only': lambda: confify([self._classpath_for_context(zinc_cc)]),
          'zinc-java': lambda: confify([self._classpath_for_context(zinc_cc)]),
          'rsc-and-zinc': lambda: confify([rsc_cc.rsc_jar_file]),
        })()
        self.context.products.get_data('rsc_mixed_compile_classpath').add_for_target(
          target,
          cp_entries)

  def create_empty_extra_products(self):
    super().create_empty_extra_products()

    compile_classpath = self.context.products.get_data('compile_classpath')
    runtime_classpath = self.context.products.get_data('runtime_classpath')
    classpath_product = self.context.products.get_data('rsc_mixed_compile_classpath')
    if not classpath_product:
      classpath_product = self.context.products.get_data(
        'rsc_mixed_compile_classpath', compile_classpath.copy)
    else:
      classpath_product.update(compile_classpath)
    classpath_product.update(runtime_classpath)

  def select(self, target):
    if not isinstance(target, JvmTarget):
      return False
    return self._classify_target_compile_workflow(target) is not None

  @memoized_method
  def _identify_workflow_tags(self, target):
    try:
      all_tags = [self._compiler_tags.get(tag) for tag in target.tags]
      filtered_tags = filter(None, all_tags)
      return assert_single_element(list(filtered_tags))
    except StopIteration:
      return None
    except ValueError as e:
      raise ValueError('Multiple compile workflow tags specified for target {}: {}'
                       .format(target, e))

  @memoized_method
  def _classify_target_compile_workflow(self, target):
    """Return the compile workflow to use for this target."""
    # scala_library() targets may have a `.java_sources` property.
    java_sources = getattr(target, 'java_sources', [])
    if java_sources or target.has_sources('.java'):
      # If there are any java sources to compile, treat it as a java library since rsc can't outline
      # java yet.
      return self.JvmCompileWorkflowType.zinc_java
    if target.has_sources('.scala'):
      return self.get_scalar_mirrored_target_option('workflow', target)
    return None

  def _key_for_target_as_dep(self, target, workflow):
    # used for jobs that are either rsc jobs or zinc jobs run against rsc
    return workflow.resolve_for_enum_variant({
      'zinc-only': lambda: self._zinc_key_for_target(target, workflow),
      'zinc-java': lambda: self._zinc_key_for_target(target, workflow),
      'rsc-and-zinc': lambda: self._rsc_key_for_target(target),
    })()

  def _rsc_key_for_target(self, target):
    return 'rsc({})'.format(target.address.spec)

  def _zinc_key_for_target(self, target, workflow):
    return workflow.resolve_for_enum_variant({
      'zinc-only': lambda: 'zinc[zinc-only]({})'.format(target.address.spec),
      'zinc-java': lambda: 'zinc[zinc-java]({})'.format(target.address.spec),
      'rsc-and-zinc': lambda: 'zinc[rsc-and-zinc]({})'.format(target.address.spec),
    })()

  def _write_to_cache_key_for_target(self, target):
    return 'write_to_cache({})'.format(target.address.spec)

  def create_compile_jobs(self,
                          compile_target,
                          compile_contexts,
                          invalid_dependencies,
                          ivts,
                          counter,
                          runtime_classpath_product):

    def work_for_vts_rsc(vts, ctx):
      target = ctx.target
      tgt, = vts.targets

      # If we didn't hit the cache in the cache job, run rsc.
      if not vts.valid:
        counter_val = str(counter()).rjust(counter.format_length(), ' ')
        counter_str = '[{}/{}] '.format(counter_val, counter.size)
        self.context.log.info(
          counter_str,
          'Rsc-ing ',
          items_to_report_element(ctx.sources, '{} source'.format(self.name())),
          ' in ',
          items_to_report_element([t.address.reference() for t in vts.targets], 'target'),
          ' (',
          ctx.target.address.spec,
          ').')
        # This does the following
        # - Collect the rsc classpath elements, including zinc compiles of rsc incompatible targets
        #   and rsc compiles of rsc compatible targets.
        # - Run Rsc on the current target with those as dependencies.

        dependencies_for_target = list(
          DependencyContext.global_instance().dependencies_respecting_strict_deps(target))

        classpath_paths = []
        classpath_directory_digests = []
        classpath_product = self.context.products.get_data('rsc_mixed_compile_classpath')
        classpath_entries = classpath_product.get_classpath_entries_for_targets(dependencies_for_target)
        for _conf, classpath_entry in classpath_entries:
          classpath_paths.append(fast_relpath(classpath_entry.path, get_buildroot()))
          if self.HERMETIC == self.execution_strategy_enum.value and not classpath_entry.directory_digest:
            raise AssertionError(
              "ClasspathEntry {} didn't have a Digest, so won't be present for hermetic "
              "execution of rsc".format(classpath_entry)
            )
          classpath_directory_digests.append(classpath_entry.directory_digest)

        ctx.ensure_output_dirs_exist()

        with Timer() as timer:
          # Outline Scala sources into SemanticDB / scalac compatible header jars.
          # ---------------------------------------------
          rsc_jar_file_relative_path = fast_relpath(ctx.rsc_jar_file.path, get_buildroot())

          sources_snapshot = ctx.target.sources_snapshot(scheduler=self.context._scheduler)

          distribution = self._get_jvm_distribution()

          def hermetic_digest_classpath():
            jdk_libs_rel, jdk_libs_digest = self._jdk_libs_paths_and_digest(distribution)

            merged_sources_and_jdk_digest = self.context._scheduler.merge_directories(
              (jdk_libs_digest, sources_snapshot.directory_digest) + tuple(classpath_directory_digests))
            classpath_rel_jdk = classpath_paths + jdk_libs_rel
            return (merged_sources_and_jdk_digest, classpath_rel_jdk)
          def nonhermetic_digest_classpath():
            classpath_abs_jdk = classpath_paths + self._jdk_libs_abs(distribution)
            return ((EMPTY_DIRECTORY_DIGEST), classpath_abs_jdk)

          (input_digest, classpath_entry_paths) = self.execution_strategy_enum.resolve_for_enum_variant({
            self.HERMETIC: hermetic_digest_classpath,
            self.SUBPROCESS: nonhermetic_digest_classpath,
            self.NAILGUN: nonhermetic_digest_classpath,
          })()

          target_sources = ctx.sources
          args = [
                   '-cp', os.pathsep.join(classpath_entry_paths),
                   '-d', rsc_jar_file_relative_path,
                 ] + self.get_options().extra_rsc_args + target_sources

          self.write_argsfile(ctx, args)

          self._runtool(distribution, input_digest, ctx)

        self._record_target_stats(tgt,
          len(classpath_entry_paths),
          len(target_sources),
          timer.elapsed,
          False,
          'rsc'
        )

      # Update the products with the latest classes.
      self.register_extra_products_from_contexts([ctx.target], compile_contexts)

    ### Create Jobs for ExecutionGraph
    cache_doublecheck_jobs = []
    rsc_jobs = []
    zinc_jobs = []

    # Invalidated targets are a subset of relevant targets: get the context for this one.
    compile_target = ivts.target
    merged_compile_context = compile_contexts[compile_target]
    rsc_compile_context = merged_compile_context.rsc_cc
    zinc_compile_context = merged_compile_context.zinc_cc

    cache_doublecheck_key = self.exec_graph_double_check_cache_key_for_target(compile_target)

    def all_zinc_rsc_invalid_dep_keys(invalid_deps):
      """Get the rsc key for an rsc-and-zinc target, or the zinc key for a zinc-only target."""
      for tgt in invalid_deps:
        # None can occur for e.g. JarLibrary deps, which we don't need to compile as they are
        # populated in the resolve goal.
        tgt_rsc_cc = compile_contexts[tgt].rsc_cc
        if tgt_rsc_cc.workflow is not None:
          # Rely on the results of zinc compiles for zinc-compatible targets
          yield self._key_for_target_as_dep(tgt, tgt_rsc_cc.workflow)

    def make_cache_doublecheck_job(dep_keys):
      # As in JvmCompile.create_compile_jobs, we create a cache-double-check job that all "real" work
      # depends on. It depends on completion of the same dependencies as the rsc job in order to run
      # as late as possible, while still running before rsc or zinc.
      return Job(cache_doublecheck_key,
                 functools.partial(self._default_double_check_cache_for_vts, ivts),
                 dependencies=list(dep_keys))

    def make_rsc_job(target, dep_targets):
      return Job(
        key=self._rsc_key_for_target(target),
        fn=functools.partial(
          # NB: This will output to the 'rsc_mixed_compile_classpath' product via
          # self.register_extra_products_from_contexts()!
          work_for_vts_rsc,
          ivts,
          rsc_compile_context,
        ),
        # The rsc jobs depend on other rsc jobs, and on zinc jobs for targets that are not
        # processed by rsc.
        dependencies=[cache_doublecheck_key] + list(all_zinc_rsc_invalid_dep_keys(dep_targets)),
        size=self._size_estimator(rsc_compile_context.sources),
      )

    def only_zinc_invalid_dep_keys(invalid_deps):
      for tgt in invalid_deps:
        rsc_cc_tgt = compile_contexts[tgt].rsc_cc
        if rsc_cc_tgt.workflow is not None:
          yield self._zinc_key_for_target(tgt, rsc_cc_tgt.workflow)

    def make_zinc_job(target, input_product_key, output_products, dep_keys):
      return Job(
        key=self._zinc_key_for_target(target, rsc_compile_context.workflow),
        fn=functools.partial(
          self._default_work_for_vts,
          ivts,
          zinc_compile_context,
          input_product_key,
          counter,
          compile_contexts,
          CompositeProductAdder(*output_products)),
        dependencies=[cache_doublecheck_key] + list(dep_keys),
        size=self._size_estimator(zinc_compile_context.sources),
      )

    workflow = rsc_compile_context.workflow

    # Replica of JvmCompile's _record_target_stats logic
    def record(k, v):
      self.context.run_tracker.report_target_info(
        self.options_scope,
        compile_target,
        ['compile', k],
        v
      )
    record('workflow', workflow.value)
    record('execution_strategy', self.execution_strategy)

    # Create the cache doublecheck job.
    workflow.resolve_for_enum_variant({
      'zinc-only': lambda: cache_doublecheck_jobs.append(
        make_cache_doublecheck_job(list(all_zinc_rsc_invalid_dep_keys(invalid_dependencies)))
      ),
      'zinc-java': lambda: cache_doublecheck_jobs.append(
        make_cache_doublecheck_job(list(only_zinc_invalid_dep_keys(invalid_dependencies)))
      ),
      'rsc-and-zinc': lambda: cache_doublecheck_jobs.append(
        make_cache_doublecheck_job(list(all_zinc_rsc_invalid_dep_keys(invalid_dependencies)))
      ),
    })()

    # Create the rsc job.
    # Currently, rsc only supports outlining scala.
    workflow.resolve_for_enum_variant({
      'zinc-only': lambda: None,
      'zinc-java': lambda: None,
      'rsc-and-zinc': lambda: rsc_jobs.append(make_rsc_job(compile_target, invalid_dependencies)),
    })()

    # Create the zinc compile jobs.
    # - Scala zinc compile jobs depend on the results of running rsc on the scala target.
    # - Java zinc compile jobs depend on the zinc compiles of their dependencies, because we can't
    #   generate jars that make javac happy at this point.
    workflow.resolve_for_enum_variant({
      # NB: zinc-only zinc jobs run zinc and depend on rsc and/or zinc compile outputs.
      'zinc-only': lambda: zinc_jobs.append(
        make_zinc_job(
          compile_target,
          input_product_key='rsc_mixed_compile_classpath',
          output_products=[
            runtime_classpath_product,
            self.context.products.get_data('rsc_mixed_compile_classpath'),
          ],
          dep_keys=list(all_zinc_rsc_invalid_dep_keys(invalid_dependencies)))),
      # NB: javac can't read rsc output yet, so we need it to depend strictly on zinc
      # compilations of dependencies.
      'zinc-java': lambda: zinc_jobs.append(
        make_zinc_job(
          compile_target,
          input_product_key='runtime_classpath',
          output_products=[
            runtime_classpath_product,
            self.context.products.get_data('rsc_mixed_compile_classpath'),
          ],
          dep_keys=list(only_zinc_invalid_dep_keys(invalid_dependencies)))),
      'rsc-and-zinc': lambda: zinc_jobs.append(
        # NB: rsc-and-zinc jobs run zinc and depend on both rsc and zinc compile outputs.
        make_zinc_job(
          compile_target,
          input_product_key='rsc_mixed_compile_classpath',
          # NB: We want to ensure the 'runtime_classpath' product *only* contains the outputs of
          # zinc compiles, and that the 'rsc_mixed_compile_classpath' entries for rsc-compatible targets
          # *only* contain the output of an rsc compile for that target.
          output_products=[
            runtime_classpath_product,
          ],
          dep_keys=list(all_zinc_rsc_invalid_dep_keys(invalid_dependencies)),
        )),
    })()

    compile_jobs = rsc_jobs + zinc_jobs

    # Create a job that depends on all real work having completed that will eagerly write to the
    # cache by calling `vt.update()`.
    write_to_cache_job = Job(
        key=self._write_to_cache_key_for_target(compile_target),
        fn=ivts.update,
        dependencies=[job.key for job in compile_jobs],
        run_asap=True,
        on_failure=ivts.force_invalidate)

    all_jobs = cache_doublecheck_jobs + rsc_jobs + zinc_jobs + [write_to_cache_job]
    return (all_jobs, len(compile_jobs))

  class RscZincMergedCompileContexts(datatype([
      ('rsc_cc', RscCompileContext),
      ('zinc_cc', CompileContext),
  ])): pass

  def select_runtime_context(self, merged_compile_context):
    return merged_compile_context.zinc_cc

  def create_compile_context(self, target, target_workdir):
    # workdir layout:
    # rsc/
    #   - outline/ -- semanticdbs for the current target as created by rsc
    #   - m.jar    -- reified scala signature jar
    # zinc/
    #   - classes/   -- class files
    #   - z.analysis -- zinc analysis for the target
    #   - z.jar      -- final jar for the target
    #   - zinc_args  -- file containing the used zinc args
    sources = self._compute_sources_for_target(target)
    rsc_dir = os.path.join(target_workdir, "rsc")
    zinc_dir = os.path.join(target_workdir, "zinc")
    return self.RscZincMergedCompileContexts(
      rsc_cc=RscCompileContext(
        target=target,
        analysis_file=None,
        classes_dir=None,
        jar_file=None,
        args_file=os.path.join(rsc_dir, 'rsc_args'),
        rsc_jar_file=ClasspathEntry(os.path.join(rsc_dir, 'm.jar')),
        log_dir=os.path.join(rsc_dir, 'logs'),
        post_compile_merge_dir=os.path.join(rsc_dir, 'post_compile_merge_dir'),
        sources=sources,
        workflow=self._classify_target_compile_workflow(target),
      ),
      zinc_cc=CompileContext(
        target=target,
        analysis_file=os.path.join(zinc_dir, 'z.analysis'),
        classes_dir=ClasspathEntry(os.path.join(zinc_dir, 'classes'), None),
        jar_file=ClasspathEntry(os.path.join(zinc_dir, 'z.jar'), None),
        log_dir=os.path.join(zinc_dir, 'logs'),
        args_file=os.path.join(zinc_dir, 'zinc_args'),
        post_compile_merge_dir=os.path.join(zinc_dir, 'post_compile_merge_dir'),
        sources=sources,
      ))

  def _runtool_hermetic(self, main, tool_name, distribution, input_digest, ctx):
    tool_classpath_abs = self._rsc_classpath
    tool_classpath = fast_relpath_collection(tool_classpath_abs)

    jvm_options = self._jvm_options

    if self._rsc.use_native_image:
      #jvm_options = []
      if jvm_options:
        raise ValueError(
          "`{}` got non-empty jvm_options when running with a graal native-image, but this is "
          "unsupported. jvm_options received: {}".format(self.options_scope, safe_shlex_join(jvm_options))
        )
      native_image_path, native_image_snapshot = self._rsc.native_image(self.context)
      additional_snapshots = [native_image_snapshot]
      initial_args = [native_image_path]
    else:
      additional_snapshots = []
      initial_args = [
        distribution.java,
      ] + self.get_options().jvm_options + [
        '-cp', os.pathsep.join(tool_classpath),
        main,
      ]

    argfile_snapshot, = self.context._scheduler.capture_snapshots([
        PathGlobsAndRoot(
          PathGlobs([fast_relpath(ctx.args_file, get_buildroot())]),
          get_buildroot(),
        ),
      ])

    cmd = initial_args + ['@{}'.format(argfile_snapshot.files[0])]

    pathglobs = list(tool_classpath)

    if pathglobs:
      root = PathGlobsAndRoot(
        PathGlobs(tuple(pathglobs)),
        get_buildroot())
      # dont capture snapshot, if pathglobs is empty
      path_globs_input_digest = self.context._scheduler.capture_snapshots((root,))[0].directory_digest

    epr_input_files = self.context._scheduler.merge_directories(
      ((path_globs_input_digest,) if path_globs_input_digest else ())
      + ((input_digest,) if input_digest else ())
      + tuple(s.directory_digest for s in additional_snapshots)
      + (argfile_snapshot.directory_digest,))

    epr = ExecuteProcessRequest(
      argv=tuple(cmd),
      input_files=epr_input_files,
      output_files=(fast_relpath(ctx.rsc_jar_file.path, get_buildroot()),),
      output_directories=tuple(),
      timeout_seconds=15*60,
      description='run {} for {}'.format(tool_name, ctx.target),
      # TODO: These should always be unicodes
      # Since this is always hermetic, we need to use `underlying.home` because
      # ExecuteProcessRequest requires an existing, local jdk location.
      jdk_home=distribution.underlying_home,
    )
    res = self.context.execute_process_synchronously_without_raising(
      epr,
      self.name(),
      [WorkUnitLabel.COMPILER])

    if res.exit_code != 0:
      raise TaskError(res.stderr, exit_code=res.exit_code)

    # TODO: parse the output of -Xprint:timings for rsc and write it to self._record_target_stats()!

    res.output_directory_digest.dump(ctx.rsc_jar_file.path)

    ctx.rsc_jar_file = ClasspathEntry(ctx.rsc_jar_file.path, res.output_directory_digest)

    self.context._scheduler.materialize_directories((
      DirectoryToMaterialize(
        # NB the first element here is the root to materialize into, not the dir to snapshot
        get_buildroot(),
        res.output_directory_digest),
    ))

    return res

  # The classpath is parameterized so that we can have a single nailgun instance serving all of our
  # execution requests.
  def _runtool_nonhermetic(self, parent_workunit, classpath, main, tool_name, distribution, ctx):
    result = self.runjava(
      classpath=classpath,
      main=main,
      jvm_options=self.get_options().jvm_options,
      args=['@{}'.format(ctx.args_file)],
      workunit_name=tool_name,
      workunit_labels=[WorkUnitLabel.COMPILER],
      dist=distribution
    )
    if result != 0:
      raise TaskError('Running {} failed'.format(tool_name))
    runjava_workunit = None
    for c in parent_workunit.children:
      if c.name is tool_name:
        runjava_workunit = c
        break
    # TODO: figure out and document when would this happen.
    if runjava_workunit is None:
      raise Exception('couldnt find work unit for underlying execution')
    return runjava_workunit

  def _runtool(self, distribution, input_digest, ctx):
    main = 'rsc.cli.Main'
    tool_name = 'rsc'
    with self.context.new_workunit(tool_name) as wu:
      return self.execution_strategy_enum.resolve_for_enum_variant({
        self.HERMETIC: lambda: self._runtool_hermetic(
          main, tool_name, distribution, input_digest, ctx),
        self.SUBPROCESS: lambda: self._runtool_nonhermetic(
          wu, self._rsc_classpath, main, tool_name, distribution, ctx),
        self.NAILGUN: lambda: self._runtool_nonhermetic(
          wu, self._nailgunnable_combined_classpath, main, tool_name, distribution, ctx),
      })()

  _JDK_LIB_NAMES = ['rt.jar', 'dt.jar', 'jce.jar', 'tools.jar']

  @memoized_method
  def _jdk_libs_paths_and_digest(self, hermetic_dist):
    jdk_libs_rel, jdk_libs_globs = hermetic_dist.find_libs_path_globs(self._JDK_LIB_NAMES)
    jdk_libs_digest = self.context._scheduler.capture_snapshots(
      (jdk_libs_globs,))[0].directory_digest
    return (jdk_libs_rel, jdk_libs_digest)

  @memoized_method
  def _jdk_libs_abs(self, nonhermetic_dist):
    return nonhermetic_dist.find_libs(self._JDK_LIB_NAMES)
