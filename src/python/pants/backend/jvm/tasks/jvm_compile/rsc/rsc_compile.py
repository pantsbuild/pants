# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import logging
import os
import re
from collections import defaultdict

from pants.backend.jvm.subsystems.dependency_context import DependencyContext  # noqa
from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.subsystems.rsc import Rsc
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.subsystems.zinc import Zinc
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_entry import ClasspathEntry
from pants.backend.jvm.tasks.jvm_compile.compile_context import CompileContext
from pants.backend.jvm.tasks.jvm_compile.execution_graph import Job
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
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


class RscCompile(JvmCompile, MirroredTargetOptionMixin):
  """Compile Scala and Java code to classfiles using Rsc."""

  _name = 'mixed' # noqa
  compiler_name = 'rsc'

  @classmethod
  def subsystem_dependencies(cls):
    return super().subsystem_dependencies() + (
      Rsc,
    )

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

  class ZincCompileUtils:

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
      default=cls.JvmCompileWorkflowType.rsc_and_zinc, metavar='<workflow>',
      help='The workflow to use to compile JVM targets.')

    register('--extra-rsc-args', type=list, default=[],
             help='Extra arguments to pass to the rsc invocation.')

    # TODO(ity): only valid for zinc-only workflow
    register('--incremental', advanced=True, type=bool, default=True,
      help='When set, zinc will use sub-target incremental compilation, which dramatically '
           'improves compile performance while changing large targets. When unset, '
           'changed targets will be compiled with an empty output directory, as if after '
           'running clean-all.')

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

  def log_zinc_file(self, analysis_file):
    self.context.log.debug('Calling zinc on: {} ({})'
      .format(analysis_file,
      hash_file(analysis_file).upper()
      if os.path.exists(analysis_file)
      else 'nonexistent'))

  @classmethod
  def _javac_plugin_args(cls, javac_plugin_map):
    ret = []
    for plugin, args in javac_plugin_map.items():
      for arg in args:
        if ' ' in arg:
          # Note: Args are separated by spaces, and there is no way to escape embedded spaces, as
          # javac's Main does a simple split on these strings.
          raise TaskError('javac plugin args must not contain spaces '
                          '(arg {} for plugin {})'.format(arg, plugin))
      ret.append('-C-Xplugin:{} {}'.format(plugin, ' '.join(args)))
    return ret

  def _scalac_plugin_args(self, scalac_plugin_map, classpath):
    if not scalac_plugin_map:
      return []

    plugin_jar_map = self._find_scalac_plugins(list(scalac_plugin_map.keys()), classpath)
    ret = []
    for name, cp_entries in plugin_jar_map.items():
      # Note that the first element in cp_entries is the one containing the plugin's metadata,
      # meaning that this is the plugin that will be loaded, even if there happen to be other
      # plugins in the list of entries (e.g., because this plugin depends on another plugin).
      ret.append('-S-Xplugin:{}'.format(':'.join(cp_entries)))
      for arg in scalac_plugin_map[name]:
        ret.append('-S-P:{}:{}'.format(name, arg))
    return ret

  @memoized_property
  def _rsc(self):
    return Rsc.global_instance()

  @memoized_property
  def _rsc_classpath(self):
    return self.tool_classpath('rsc')

  @memoized_property
  def _zinc(self):
    return Zinc.Factory.global_instance().create(self.context.products, self.execution_strategy)

  def _get_zinc_compiler_classpath(self):
    """Get the classpath for the zinc compiler JVM tool.

    This will just be the zinc compiler tool classpath normally, but tasks which invoke zinc along
    with other JVM tools with nailgun (such as RscCompile) require zinc to be invoked with this
    method to ensure a single classpath is used for all the tools they need to invoke so that the
    nailgun instance (which is keyed by classpath and JVM options) isn't invalidated.
    """
    return [self._zinc.zinc]

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
    cp.extend(self._get_zinc_compiler_classpath())
    return cp

  # Overrides the normal zinc compiler classpath, which only contains zinc.
  def get_zinc_compiler_classpath(self):
    return self.execution_strategy_enum.resolve_for_enum_variant({
      # NB: We must use the verbose version of super() here, possibly because of the lambda.
      self.HERMETIC: lambda: self._get_zinc_compiler_classpath(),
      self.SUBPROCESS: lambda: self._get_zinc_compiler_classpath(),
      self.NAILGUN: lambda: self._nailgunnable_combined_classpath,
    })()

  def _get_zinc_arguments(self, settings):
    distribution = self._get_jvm_distribution()
    return self._format_zinc_arguments(settings, distribution)

  @staticmethod
  def _format_zinc_arguments(settings, distribution):
    """Extracts and formats the zinc arguments given in the jvm platform settings.

    This is responsible for the symbol substitution which replaces $JAVA_HOME with the path to an
    appropriate jvm distribution.

    :param settings: The jvm platform settings from which to extract the arguments.
    :type settings: :class:`JvmPlatformSettings`
    """
    zinc_args = [
      '-C-source', '-C{}'.format(settings.source_level),
      '-C-target', '-C{}'.format(settings.target_level),
    ]
    if settings.args:
      settings_args = settings.args
      if any('$JAVA_HOME' in a for a in settings.args):
        logger.debug('Substituting "$JAVA_HOME" with "{}" in jvm-platform args.'
          .format(distribution.home))
        settings_args = (a.replace('$JAVA_HOME', distribution.home) for a in settings.args)
      zinc_args.extend(settings_args)
    return zinc_args

  # NB: Override of JvmCompile method!
  def register_extra_products_from_contexts(self, targets, compile_contexts):
    super().register_extra_products_from_contexts(targets, compile_contexts)

    self.register_zinc_products(targets, compile_contexts)
    def confify(entries):
      return [(conf, e) for e in entries for conf in self._confs]

    # Ensure that the jar/rsc jar is on the rsc_mixed_compile_classpath.
    for target in targets:
      merged_cc = compile_contexts[target]
      rsc_cc = merged_cc.rsc_cc
      zinc_cc = merged_cc.zinc_cc
      if rsc_cc.workflow is not None:
        cp_entries = rsc_cc.workflow.resolve_for_enum_variant({
          'zinc-only': lambda: confify([zinc_cc.jar_file]),
          'zinc-java': lambda: confify([zinc_cc.jar_file]),
          'rsc-and-zinc': lambda: confify([rsc_cc.rsc_jar_file]),
        })()
        self.context.products.get_data('rsc_mixed_compile_classpath').add_for_target(
          target,
          cp_entries)

  def register_zinc_products(self, targets, compile_contexts):
    compile_contexts = [self.select_runtime_context(compile_contexts[t]) for t in targets]
    zinc_analysis = self.context.products.get_data('zinc_analysis')
    zinc_args = self.context.products.get_data('zinc_args')

    if zinc_analysis is not None:
      for compile_context in compile_contexts:
        zinc_analysis[compile_context.target] = (compile_context.classes_dir.path,
        compile_context.jar_file.path,
        compile_context.analysis_file)

    if zinc_args is not None:
      for compile_context in compile_contexts:
        with open(compile_context.args_file, 'r') as fp:
          args = fp.read().split()
        zinc_args[compile_context.target] = args

  def create_empty_extra_products(self):
    super().create_empty_extra_products()

    self.create_empty_extra_zinc_products()
    compile_classpath = self.context.products.get_data('compile_classpath')
    runtime_classpath = self.context.products.get_data('runtime_classpath')
    classpath_product = self.context.products.get_data('rsc_mixed_compile_classpath')
    if not classpath_product:
      classpath_product = self.context.products.get_data(
        'rsc_mixed_compile_classpath', compile_classpath.copy)
    else:
      classpath_product.update(compile_classpath)
    classpath_product.update(runtime_classpath)

  def create_empty_extra_zinc_products(self):
    if self.context.products.is_required_data('zinc_analysis'):
      self.context.products.safe_create_data('zinc_analysis', dict)

    if self.context.products.is_required_data('zinc_args'):
      self.context.products.safe_create_data('zinc_args', lambda: defaultdict(list))

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

  def create_compile_jobs(self,
                          compile_target,
                          compile_contexts,
                          invalid_dependencies,
                          ivts,
                          counter,
                          runtime_classpath_product):

    def work_for_vts_rsc(vts, ctx):
      # Double check the cache before beginning compilation
      hit_cache = self.check_cache(vts, counter)
      target = ctx.target
      tgt, = vts.targets

      if not hit_cache:
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
          if classpath_entry.directory_digest:
            classpath_directory_digests.append(classpath_entry.directory_digest)
          else:
            logger.warning(
              "ClasspathEntry {} didn't have a Digest, so won't be present for hermetic "
              "execution of rsc".format(classpath_entry)
            )

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
    rsc_jobs = []
    zinc_jobs = []

    # Invalidated targets are a subset of relevant targets: get the context for this one.
    compile_target = ivts.target
    merged_compile_context = compile_contexts[compile_target]
    rsc_compile_context = merged_compile_context.rsc_cc
    zinc_compile_context = merged_compile_context.zinc_cc

    def all_zinc_rsc_invalid_dep_keys(invalid_deps):
      """Get the rsc key for an rsc-and-zinc target, or the zinc key for a zinc-only target."""
      for tgt in invalid_deps:
        # None can occur for e.g. JarLibrary deps, which we don't need to compile as they are
        # populated in the resolve goal.
        tgt_rsc_cc = compile_contexts[tgt].rsc_cc
        if tgt_rsc_cc.workflow is not None:
          # Rely on the results of zinc compiles for zinc-compatible targets
          yield self._key_for_target_as_dep(tgt, tgt_rsc_cc.workflow)

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
        dependencies=list(all_zinc_rsc_invalid_dep_keys(dep_targets)),
        size=self._size_estimator(rsc_compile_context.sources),
        on_success=ivts.update,
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
        dependencies=list(dep_keys),
        size=self._size_estimator(zinc_compile_context.sources),
        # If compilation and analysis work succeeds, validate the vts.
        # Otherwise, fail it.
        on_success=ivts.update,
        on_failure=ivts.force_invalidate)

    # Create the rsc job.
    # Currently, rsc only supports outlining scala.
    workflow = rsc_compile_context.workflow
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

    return rsc_jobs + zinc_jobs

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

  def _verify_zinc_classpath(self, classpath, allow_dist=True):
    def is_outside(path, putative_parent):
      return os.path.relpath(path, putative_parent).startswith(os.pardir)

    dist = self._zinc.dist
    for path in classpath:
      if not os.path.isabs(path):
        raise TaskError('Classpath entries provided to zinc should be absolute. '
                        '{} is not.'.format(path))

      if is_outside(path, self.get_options().pants_workdir) and (not allow_dist or is_outside(path, dist.home)):
        raise TaskError('Classpath entries provided to zinc should be in working directory or '
                        'part of the JDK. {} is not.'.format(path))
      if path != os.path.normpath(path):
        raise TaskError('Classpath entries provided to zinc should be normalized '
                        '(i.e. without ".." and "."). {} is not.'.format(path))

  def javac_classpath(self):
    # Note that if this classpath is empty then Zinc will automatically use the javac from
    # the JDK it was invoked with.
    return Java.global_javac_classpath(self.context.products)

  def scalac_classpath_entries(self):
    """Returns classpath entries for the scalac classpath."""
    return ScalaPlatform.global_instance().compiler_classpath_entries(
      self.context.products, self.context._scheduler)

  def compile(self, ctx, args, dependency_classpath, upstream_analysis,
    settings, compiler_option_sets, zinc_file_manager,
    javac_plugin_map, scalac_plugin_map):
    absolute_classpath = (ctx.classes_dir.path,) + tuple(ce.path for ce in dependency_classpath)

    if self.get_options().capture_classpath:
      self._record_compile_classpath(absolute_classpath, ctx.target, ctx.classes_dir.path)

    self._verify_zinc_classpath(absolute_classpath, allow_dist=(self.execution_strategy != self.HERMETIC))
    # TODO: Investigate upstream_analysis for hermetic compiles
    self._verify_zinc_classpath(upstream_analysis.keys())

    def relative_to_exec_root(path):
      # TODO: Support workdirs not nested under buildroot by path-rewriting.
      return fast_relpath(path, get_buildroot())

    analysis_cache = relative_to_exec_root(ctx.analysis_file)
    classes_dir = relative_to_exec_root(ctx.classes_dir.path)
    jar_file = relative_to_exec_root(ctx.jar_file.path)
    # TODO: Have these produced correctly, rather than having to relativize them here
    relative_classpath = tuple(relative_to_exec_root(c) for c in absolute_classpath)

    # list of classpath entries
    scalac_classpath_entries = self.scalac_classpath_entries()
    scala_path = [relative_to_exec_root(classpath_entry.path) for classpath_entry in scalac_classpath_entries]

    zinc_args = []
    zinc_args.extend([
      '-log-level', self.get_options().level,
      '-analysis-cache', analysis_cache,
      '-classpath', ':'.join(relative_classpath),
      '-d', classes_dir,
      '-jar', jar_file,
    ])
    if not self.get_options().colors:
      zinc_args.append('-no-color')

    if self.post_compile_extra_resources(ctx):
      post_compile_merge_dir = relative_to_exec_root(ctx.post_compile_merge_dir)
      zinc_args.extend(['--post-compile-merge-dir', post_compile_merge_dir])

    compiler_bridge_classpath_entry = self._zinc.compile_compiler_bridge(self.context)
    zinc_args.extend(['-compiled-bridge-jar', relative_to_exec_root(compiler_bridge_classpath_entry.path)])
    zinc_args.extend(['-scala-path', ':'.join(scala_path)])

    zinc_args.extend(self._javac_plugin_args(javac_plugin_map))
    # Search for scalac plugins on the classpath.
    # Note that:
    # - We also search in the extra scalac plugin dependencies, if specified.
    # - In scala 2.11 and up, the plugin's classpath element can be a dir, but for 2.10 it must be
    #   a jar.  So in-repo plugins will only work with 2.10 if --use-classpath-jars is true.
    # - We exclude our own classes_dir/jar_file, because if we're a plugin ourselves, then our
    #   classes_dir doesn't have scalac-plugin.xml yet, and we don't want that fact to get
    #   memoized (which in practice will only happen if this plugin uses some other plugin, thus
    #   triggering the plugin search mechanism, which does the memoizing).
    scalac_plugin_search_classpath = (
      (set(absolute_classpath) | set(self.scalac_plugin_classpath_elements())) -
      {ctx.classes_dir.path, ctx.jar_file.path}
    )
    zinc_args.extend(self._scalac_plugin_args(scalac_plugin_map, scalac_plugin_search_classpath))
    if upstream_analysis:
      zinc_args.extend(['-analysis-map',
        ','.join('{}:{}'.format(
          relative_to_exec_root(k),
          relative_to_exec_root(v)
        ) for k, v in upstream_analysis.items())])

    zinc_args.extend(args)
    zinc_args.extend(self._get_zinc_arguments(settings))
    zinc_args.append('-transactional')

    compiler_option_sets_args = self.get_merged_args_for_compiler_option_sets(compiler_option_sets)
    zinc_args.extend(compiler_option_sets_args)

    if not self._clear_invalid_analysis:
      zinc_args.append('-no-clear-invalid-analysis')

    if not zinc_file_manager:
      zinc_args.append('-no-zinc-file-manager')

    jvm_options = []

    if self.javac_classpath():
      # Make the custom javac classpath the first thing on the bootclasspath, to ensure that
      # it's the one javax.tools.ToolProvider.getSystemJavaCompiler() loads.
      # It will probably be loaded even on the regular classpath: If not found on the bootclasspath,
      # getSystemJavaCompiler() constructs a classloader that loads from the JDK's tools.jar.
      # That classloader will first delegate to its parent classloader, which will search the
      # regular classpath.  However it's harder to guarantee that our javac will preceed any others
      # on the classpath, so it's safer to prefix it to the bootclasspath.
      jvm_options.extend(['-Xbootclasspath/p:{}'.format(':'.join(self.javac_classpath()))])

    jvm_options.extend(self._jvm_options)

    zinc_args.extend(ctx.sources)

    self.log_zinc_file(ctx.analysis_file)
    self.write_argsfile(ctx, zinc_args)

    return self.execution_strategy_enum.resolve_for_enum_variant({
      self.HERMETIC: lambda: self._compile_hermetic(
        jvm_options, ctx, classes_dir, jar_file, compiler_bridge_classpath_entry,
        dependency_classpath, scalac_classpath_entries),
      self.SUBPROCESS: lambda: self._compile_nonhermetic(jvm_options, ctx, classes_dir),
      self.NAILGUN: lambda: self._compile_nonhermetic(jvm_options, ctx, classes_dir),
    })()

  class ZincCompileError(TaskError):
    """An exception type specifically to signal a failed zinc execution."""

  def _compile_nonhermetic(self, jvm_options, ctx, classes_directory):
    # Populate the resources to merge post compile onto disk for the nonhermetic case,
    # where `--post-compile-merge-dir` was added is the relevant part.
    self.context._scheduler.materialize_directories((
      DirectoryToMaterialize(get_buildroot(), self.post_compile_extra_resources_digest(ctx)),
    ))

    exit_code = self.runjava(classpath=self.get_zinc_compiler_classpath(),
      main=Zinc.ZINC_COMPILE_MAIN,
      jvm_options=jvm_options,
      args=['@{}'.format(ctx.args_file)],
      workunit_name=self.name(),
      workunit_labels=[WorkUnitLabel.COMPILER],
      dist=self._zinc.dist)
    if exit_code != 0:
      raise self.ZincCompileError('Zinc compile failed.', exit_code=exit_code)

  def _compile_hermetic(self, jvm_options, ctx, classes_dir, jar_file,
    compiler_bridge_classpath_entry, dependency_classpath,
    scalac_classpath_entries):
    zinc_relpath = fast_relpath(self._zinc.zinc, get_buildroot())

    snapshots = [
      self._zinc.snapshot(self.context._scheduler),
      ctx.target.sources_snapshot(self.context._scheduler),
    ]

    # scala_library() targets with java_sources have circular dependencies on those java source
    # files, and we provide them to the same zinc command line that compiles the scala, so we need
    # to make sure those source files are available in the hermetic execution sandbox.
    java_sources_targets = getattr(ctx.target, 'java_sources', [])
    java_sources_snapshots = [
      tgt.sources_snapshot(self.context._scheduler)
      for tgt in java_sources_targets
    ]
    snapshots.extend(java_sources_snapshots)

    # Ensure the dependencies and compiler bridge jars are available in the execution sandbox.
    relevant_classpath_entries = dependency_classpath + [compiler_bridge_classpath_entry]
    directory_digests = tuple(
      entry.directory_digest for entry in relevant_classpath_entries if entry.directory_digest
    )
    if len(directory_digests) != len(relevant_classpath_entries):
      for dep in relevant_classpath_entries:
        if dep.directory_digest is None:
          logger.warning(
            "ClasspathEntry {} didn't have a Digest, so won't be present for hermetic "
            "execution of zinc".format(dep)
          )
    snapshots.extend(
      classpath_entry.directory_digest for classpath_entry in scalac_classpath_entries
    )

    if self._zinc.use_native_image:
      if jvm_options:
        raise ValueError(
          "`{}` got non-empty jvm_options when running with a graal native-image, but this is "
          "unsupported. jvm_options received: {}".format(self.options_scope, safe_shlex_join(jvm_options))
        )
      native_image_path, native_image_snapshot = self._zinc.native_image(self.context)
      native_image_snapshots = (native_image_snapshot.directory_digest,)
      scala_boot_classpath = [
                               classpath_entry.path for classpath_entry in scalac_classpath_entries
                             ] + [
                               # We include rt.jar on the scala boot classpath because the compiler usually gets its
                               # contents from the VM it is executing in, but not in the case of a native image. This
                               # resolves a `object java.lang.Object in compiler mirror not found.` error.
                               '.jdk/jre/lib/rt.jar',
                               # The same goes for the jce.jar, which provides javax.crypto.
                               '.jdk/jre/lib/jce.jar',
                             ]
      image_specific_argv =  [
        native_image_path,
        '-java-home', '.jdk',
        '-Dscala.boot.class.path={}'.format(os.pathsep.join(scala_boot_classpath)),
        '-Dscala.usejavacp=true',
      ]
    else:
      # TODO: Extract something common from Executor._create_command to make the command line
      # TODO: Lean on distribution for the bin/java appending here
      native_image_snapshots = ()
      image_specific_argv =  ['.jdk/bin/java'] + jvm_options + [
        '-cp', zinc_relpath,
        Zinc.ZINC_COMPILE_MAIN
      ]

    argfile_snapshot, = self.context._scheduler.capture_snapshots([
      PathGlobsAndRoot(
        PathGlobs([fast_relpath(ctx.args_file, get_buildroot())]),
        get_buildroot(),
      ),
    ])

    argv = image_specific_argv + ['@{}'.format(argfile_snapshot.files[0])]

    merged_input_digest = self.context._scheduler.merge_directories(
      tuple(s.directory_digest for s in snapshots) +
      directory_digests +
      native_image_snapshots +
      (self.post_compile_extra_resources_digest(ctx), argfile_snapshot.directory_digest)
    )

    req = ExecuteProcessRequest(
      argv=tuple(argv),
      input_files=merged_input_digest,
      output_files=(jar_file,) if self.get_options().use_classpath_jars else (),
      output_directories=() if self.get_options().use_classpath_jars else (classes_dir,),
      description="zinc compile for {}".format(ctx.target.address.spec),
      jdk_home=self._zinc.underlying_dist.home,
    )
    res = self.context.execute_process_synchronously_or_raise(
      req, self.name(), [WorkUnitLabel.COMPILER])

    # TODO: Materialize as a batch in do_compile or somewhere
    self.context._scheduler.materialize_directories((
      DirectoryToMaterialize(get_buildroot(), res.output_directory_digest),
    ))

    # TODO: This should probably return a ClasspathEntry rather than a Digest
    return res.output_directory_digest

  @memoized_method
  def _jdk_libs_paths_and_digest(self, hermetic_dist):
    jdk_libs_rel, jdk_libs_globs = hermetic_dist.find_libs_path_globs(self._JDK_LIB_NAMES)
    jdk_libs_digest = self.context._scheduler.capture_snapshots(
      (jdk_libs_globs,))[0].directory_digest
    return (jdk_libs_rel, jdk_libs_digest)

  @memoized_method
  def _jdk_libs_abs(self, nonhermetic_dist):
    return nonhermetic_dist.find_libs(self._JDK_LIB_NAMES)

  # TODO: rename this, make it public, and explain what "searching for invalid targets" refers to!
  def _on_invalid_compile_dependency(self, dep, compile_target, contexts):
    """Decide whether to continue searching for invalid targets to use in the execution graph.

    If a necessary dep is a rsc-and-zinc dep and the root is a zinc-only one, continue to recurse
    because otherwise we'll drop the path between Zinc compile of the zinc-only target and a Zinc
    compile of a transitive rsc-and-zinc dependency.

    This is only an issue for graphs like J -> S1 -> S2, where J is a zinc-only target,
    S1/2 are rsc-and-zinc targets and S2 must be on the classpath to compile J successfully.
    """
    def dep_has_rsc_compile():
      return contexts[dep].rsc_cc.workflow == self.JvmCompileWorkflowType.rsc_and_zinc
    return contexts[compile_target].rsc_cc.workflow.resolve_for_enum_variant({
      'zinc-java': dep_has_rsc_compile,
      'zinc-only': dep_has_rsc_compile,
      'rsc-and-zinc': lambda: False
    })()

  def select_source(self, source_file_path):
    return source_file_path.endswith('.java') or source_file_path.endswith('.scala')
