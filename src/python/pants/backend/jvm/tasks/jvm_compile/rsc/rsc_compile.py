# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import json
import logging
import os
import re

from six import text_type

from pants.backend.jvm.subsystems.dependency_context import DependencyContext  # noqa
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_entry import ClasspathEntry
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_compile.compile_context import CompileContext
from pants.backend.jvm.tasks.jvm_compile.execution_graph import Job
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.engine.fs import Digest, DirectoryToMaterialize, PathGlobs, PathGlobsAndRoot
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.java.jar.jar_dependency import JarDependency
from pants.reporting.reporting_utils import items_to_report_element
from pants.util.contextutil import Timer
from pants.util.dirutil import (fast_relpath, fast_relpath_optional, maybe_read_file,
                                safe_file_dump, safe_mkdir)


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


def dump_digest(output_dir, digest):
  safe_file_dump('{}.digest'.format(output_dir),
    '{}:{}'.format(digest.fingerprint, digest.serialized_bytes_length))


def load_digest(output_dir):
  read_file = maybe_read_file('{}.digest'.format(output_dir))
  if read_file:
    fingerprint, length = read_file.split(':')
    return Digest(fingerprint, int(length))
  else:
    return None


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


def _paths_from_classpath(classpath_tuples, collection_type=list):
  return collection_type(y[1] for y in classpath_tuples)


class RscCompileContext(CompileContext):
  def __init__(self,
               target,
               analysis_file,
               classes_dir,
               rsc_mjar_file,
               jar_file,
               log_dir,
               zinc_args_file,
               sources,
               rsc_index_dir):
    super(RscCompileContext, self).__init__(target, analysis_file, classes_dir, jar_file,
                                               log_dir, zinc_args_file, sources)
    self.rsc_mjar_file = rsc_mjar_file
    self.rsc_index_dir = rsc_index_dir

  def ensure_output_dirs_exist(self):
    safe_mkdir(os.path.dirname(self.rsc_mjar_file))
    safe_mkdir(self.rsc_index_dir)


class RscCompile(ZincCompile):
  """Compile Scala and Java code to classfiles using Rsc."""

  _name = 'rsc' # noqa
  compiler_name = 'rsc'

  def __init__(self, *args, **kwargs):
    super(RscCompile, self).__init__(*args, **kwargs)
    self._metacp_jars_classpath_product = ClasspathProducts(self.get_options().pants_workdir)

  @classmethod
  def implementation_version(cls):
    return super(RscCompile, cls).implementation_version() + [('RscCompile', 170)]

  @classmethod
  def register_options(cls, register):
    super(RscCompile, cls).register_options(register)

    rsc_toolchain_version = '0.0.0-446-c64e6937'
    scalameta_toolchain_version = '4.0.0'

    cls.register_jvm_tool(
      register,
      'rsc',
      classpath=[
          JarDependency(
              org='com.twitter',
              name='rsc_2.11',
              rev=rsc_toolchain_version,
          ),
      ],
      custom_rules=[
        Shader.exclude_package('rsc', recursive=True),
      ])
    cls.register_jvm_tool(
      register,
      'metacp',
      classpath=[
          JarDependency(
            org='org.scalameta',
            name='metacp_2.11',
            rev=scalameta_toolchain_version,
          ),
      ],
      custom_rules=[
        Shader.exclude_package('scala', recursive=True),
      ])
    cls.register_jvm_tool(
      register,
      'metai',
      classpath=[
          JarDependency(
            org='org.scalameta',
            name='metai_2.11',
            rev=scalameta_toolchain_version,
          ),
      ],
      custom_rules=[
        Shader.exclude_package('scala', recursive=True),
      ])

  def register_extra_products_from_contexts(self, targets, compile_contexts):
    super(RscCompile, self).register_extra_products_from_contexts(targets, compile_contexts)
    def pathglob_for(filename):
      return PathGlobsAndRoot(
        PathGlobs(
          (fast_relpath_optional(filename, get_buildroot()),)),
        text_type(get_buildroot()))

    def to_classpath_entries(paths, scheduler):
      # list of path ->
      # list of (path, optional<digest>) ->
      path_and_digests = [(p, load_digest(os.path.dirname(p))) for p in paths]
      # partition: list of path, list of tuples
      paths_without_digests = [p for (p, d) in path_and_digests if not d]
      if paths_without_digests:
        self.context.log.debug('Expected to find digests for {}, capturing them.'
                               .format(paths_without_digests))
      paths_with_digests = [(p, d) for (p, d) in path_and_digests if d]
      # list of path -> list path, captured snapshot -> list of path with digest
      snapshots = scheduler.capture_snapshots(tuple(pathglob_for(p) for p in paths_without_digests))
      captured_paths_and_digests = [(p, s.directory_digest)
                                    for (p, s) in zip(paths_without_digests, snapshots)]
      # merge and classpath ify
      return [ClasspathEntry(p, d) for (p, d) in paths_with_digests + captured_paths_and_digests]

    def confify(entries):
      return [(conf, e) for e in entries for conf in self._confs]

    for target in targets:
      rsc_cc, compile_cc = compile_contexts[target]
      if self._only_zinc_compileable(target):
        self.context.products.get_data('rsc_classpath').add_for_target(
          compile_cc.target,
          confify([compile_cc.jar_file])
        )
      elif self._rsc_compilable(target):
        self.context.products.get_data('rsc_classpath').add_for_target(
          rsc_cc.target,
          confify(to_classpath_entries([rsc_cc.rsc_mjar_file], self.context._scheduler)))
      elif self._metacpable(target):
        # Walk the metacp results dir and add classpath entries for all the files there.
        # TODO exercise this with a test.
        # TODO, this should only list the files/directories in the first directory under the index dir

        elements_in_index_dir = [os.path.join(rsc_cc.rsc_index_dir, s)
                                 for s in os.listdir(rsc_cc.rsc_index_dir)]

        entries = to_classpath_entries(elements_in_index_dir, self.context._scheduler)
        self._metacp_jars_classpath_product.add_for_target(
          rsc_cc.target, confify(entries))
      else:
        pass

  def _metacpable(self, target):
    return isinstance(target, JarLibrary)

  def _rsc_compilable(self, target):
    return target.has_sources('.scala') and not target.has_sources('.java')

  def _only_zinc_compileable(self, target):
    return target.has_sources('.java')

  def _is_scala_core_library(self, target):
    return target.address.spec in ('//:scala-library', '//:scala-library-synthetic')

  def create_empty_extra_products(self):
    super(RscCompile, self).create_empty_extra_products()

    compile_classpath = self.context.products.get_data('compile_classpath')
    classpath_product = self.context.products.get_data('rsc_classpath')
    if not classpath_product:
      self.context.products.get_data('rsc_classpath', compile_classpath.copy)
    else:
      classpath_product.update(compile_classpath)

  def select(self, target):
    # Require that targets are marked for JVM compilation, to differentiate from
    # targets owned by the scalajs contrib module.
    if self._metacpable(target):
      return True
    if not isinstance(target, JvmTarget):
      return False
    return self._only_zinc_compileable(target) or self._rsc_compilable(target)

  def _rsc_key_for_target(self, compile_target):
    if self._only_zinc_compileable(compile_target):
      # rsc outlining with java dependencies depend on the java's zinc compile
      return self._compile_against_rsc_key_for_target(compile_target)
    elif self._rsc_compilable(compile_target):
      return "rsc({})".format(compile_target.address.spec)
    elif self._metacpable(compile_target):
      return "metacp({})".format(compile_target.address.spec)
    else:
      raise TaskError('unexpected target for compiling with rsc .... {}'.format(compile_target))

  def _compile_against_rsc_key_for_target(self, compile_target):
    return "compile_against_rsc({})".format(compile_target.address.spec)

  def pre_compile_jobs(self, counter):

    # Create a target for the jdk outlining so that it'll only be done once per run.
    target = Target('jdk', Address('', 'jdk'), self.context.build_graph)
    index_dir = os.path.join(self.versioned_workdir, '--jdk--', 'index')

    def work_for_vts_rsc_jdk():
      distribution = self._get_jvm_distribution()
      jvm_lib_jars_abs = distribution.find_libs(['rt.jar', 'dt.jar', 'jce.jar', 'tools.jar'])
      self._jvm_lib_jars_abs = jvm_lib_jars_abs

      metacp_inputs = tuple(jvm_lib_jars_abs)

      counter_val = str(counter()).rjust(counter.format_length(), b' ')
      counter_str = '[{}/{}] '.format(counter_val, counter.size)
      self.context.log.info(
        counter_str,
        'Metacp-ing ',
        items_to_report_element(metacp_inputs, 'jar'),
        ' in the jdk')

      # NB: Metacp doesn't handle the existence of possibly stale semanticdb jars,
      # so we explicitly clean the directory to keep it happy.
      safe_mkdir(index_dir, clean=True)

      with Timer() as timer:
        # Step 1: Convert classpath to SemanticDB
        # ---------------------------------------
        rsc_index_dir = fast_relpath(index_dir, get_buildroot())
        args = [
          '--verbose',
          # NB: The directory to dump the semanticdb jars generated by metacp.
          '--out', rsc_index_dir,
          os.pathsep.join(metacp_inputs),
        ]
        metacp_wu = self._runtool(
          'scala.meta.cli.Metacp',
          'metacp',
          args,
          distribution,
          tgt=target,
          input_files=tuple(
            # NB: no input files because the jdk is expected to exist on the system in a known
            #     location.
            #     Related: https://github.com/pantsbuild/pants/issues/6416
          ),
          output_dir=rsc_index_dir)
        metacp_stdout = stdout_contents(metacp_wu)
        metacp_result = json.loads(metacp_stdout)

        metai_classpath = self._collect_metai_classpath(metacp_result, jvm_lib_jars_abs)

        # Step 1.5: metai Index the semanticdbs
        # -------------------------------------
        self._run_metai_tool(distribution, metai_classpath, rsc_index_dir, tgt=target)

        self._jvm_lib_metacp_classpath = [os.path.join(get_buildroot(), x) for x in metai_classpath]

      self._record_target_stats(target,
        len(self._jvm_lib_metacp_classpath),
        len([]),
        timer.elapsed,
        False,
        'metacp'
      )

    return [
      Job(
        'metacp(jdk)',
        functools.partial(
          work_for_vts_rsc_jdk
        ),
        [],
        self._size_estimator([]),
      ),
    ]

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
        counter_val = str(counter()).rjust(counter.format_length(), b' ')
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
        # - collect jar dependencies and metacp-classpath entries for them
        # - collect the non-java targets and their classpath entries
        # - break out java targets and their javac'd classpath entries
        # metacp
        # - metacp the java targets
        # rsc
        # - combine the metacp outputs for jars, previous scala targets and the java metacp
        #   classpath
        # - run Rsc on the current target with those as dependencies

        dependencies_for_target = list(
          DependencyContext.global_instance().dependencies_respecting_strict_deps(target))

        jar_deps = [t for t in dependencies_for_target if isinstance(t, JarLibrary)]

        def is_java_compile_target(t):
          return isinstance(t, JavaLibrary) or t.has_sources('.java')
        java_deps = [t for t in dependencies_for_target
                     if is_java_compile_target(t)]
        non_java_deps = [t for t in dependencies_for_target
                         if not (is_java_compile_target(t)) and not isinstance(t, JarLibrary)]

        metacped_jar_classpath_abs = _paths_from_classpath(
          self._metacp_jars_classpath_product.get_for_targets(jar_deps)
        )
        metacped_jar_classpath_abs.extend(self._jvm_lib_metacp_classpath)
        metacped_jar_classpath_rel = fast_relpath_collection(metacped_jar_classpath_abs)

        jar_rsc_classpath_paths = _paths_from_classpath(
          self.context.products.get_data('rsc_classpath').get_for_targets(jar_deps),
          collection_type=set)
        jar_rsc_classpath_rel = fast_relpath_collection(jar_rsc_classpath_paths)

        non_java_paths = _paths_from_classpath(
          self.context.products.get_data('rsc_classpath').get_for_targets(non_java_deps),
          collection_type=set)
        non_java_rel = fast_relpath_collection(non_java_paths)

        java_paths = _paths_from_classpath(
          self.context.products.get_data('rsc_classpath').get_for_targets(java_deps),
          collection_type=set)
        java_rel = fast_relpath_collection(java_paths)

        ctx.ensure_output_dirs_exist()

        distribution = self._get_jvm_distribution()
        with Timer() as timer:
          # Step 1: Convert classpath to SemanticDB
          # ---------------------------------------
          # If there are any as yet not metacp'd dependencies, metacp them so their indices can
          # be passed to Rsc.
          # TODO move these to their own jobs. https://github.com/pantsbuild/pants/issues/6754

          # Inputs
          # - Java dependencies jars
          metacp_inputs = java_rel

          # Dependencies
          # - 3rdparty jars
          # - non-java, ie scala, dependencies
          # - jdk
          snapshotable_metacp_dependencies = list(jar_rsc_classpath_rel) + \
                                list(non_java_rel) + \
                                fast_relpath_collection(
                                  _paths_from_classpath(self._extra_compile_time_classpath))
          metacp_dependencies = snapshotable_metacp_dependencies + self._jvm_lib_jars_abs

          if metacp_inputs:
            rsc_index_dir = fast_relpath(ctx.rsc_index_dir, get_buildroot())
            args = [
              '--verbose',
              '--stub-broken-signatures',
              '--dependency-classpath', os.pathsep.join(metacp_dependencies),
              # NB: The directory to dump the semanticdb jars generated by metacp.
              '--out', rsc_index_dir,
              os.pathsep.join(metacp_inputs),
            ]
            metacp_wu = self._runtool(
              'scala.meta.cli.Metacp',
              'metacp',
              args,
              distribution,
              tgt=tgt,
              input_files=tuple(metacp_inputs + snapshotable_metacp_dependencies),
              output_dir=rsc_index_dir)
            metacp_stdout = stdout_contents(metacp_wu)
            metacp_result = json.loads(metacp_stdout)

            metacped_java_dependency_rel = self._collect_metai_classpath(metacp_result,
              java_rel)

            # Step 1.5: metai Index the semanticdbs
            # -------------------------------------
            self._run_metai_tool(distribution, metacped_java_dependency_rel, rsc_index_dir, tgt)
          else:
            # NB: there are no unmetacp'd dependencies
            metacped_java_dependency_rel = []


          # Step 2: Outline Scala sources into SemanticDB
          # ---------------------------------------------
          rsc_mjar_file = fast_relpath(ctx.rsc_mjar_file, get_buildroot())

          # TODO remove non-rsc entries from non_java_rel in a better way
          rsc_semanticdb_classpath = metacped_java_dependency_rel + \
                                     metacped_jar_classpath_rel + \
                                     [j for j in non_java_rel if 'compile/rsc/' in j]
          target_sources = ctx.sources
          args = [
                   '-cp', os.pathsep.join(rsc_semanticdb_classpath),
                   '-d', rsc_mjar_file,
                 ] + target_sources
          sources_snapshot = ctx.target.sources_snapshot(scheduler=self.context._scheduler)
          self._runtool(
            'rsc.cli.Main',
            'rsc',
            args,
            distribution,
            tgt=tgt,
            input_files=tuple(rsc_semanticdb_classpath),
            input_digest=sources_snapshot.directory_digest,
            output_dir=os.path.dirname(rsc_mjar_file))

        self._record_target_stats(tgt,
          len(metacp_inputs),
          len(target_sources),
          timer.elapsed,
          False,
          'rsc'
        )
        # Write any additional resources for this target to the target workdir.
        self.write_extra_resources(ctx)

      # Update the products with the latest classes.
      self.register_extra_products_from_contexts([ctx.target], compile_contexts)

    def work_for_vts_rsc_jar_library(vts, ctx):
      metacp_dependencies_entries = self._zinc.compile_classpath_entries(
        'compile_classpath',
        ctx.target,
        extra_cp_entries=self._extra_compile_time_classpath)

      metacp_dependencies = fast_relpath_collection(c.path for c in metacp_dependencies_entries)


      metacp_dependencies_digests = [c.directory_digest for c in metacp_dependencies_entries
                                     if c.directory_digest]
      metacp_dependencies_paths_without_digests = fast_relpath_collection(
        c.path for c in metacp_dependencies_entries if not c.directory_digest)

      classpath_entries = [
        cp_entry for (conf, cp_entry) in
        self.context.products.get_data('compile_classpath').get_classpath_entries_for_targets(
          [ctx.target])
      ]
      classpath_digests = [c.directory_digest for c in classpath_entries if c.directory_digest]
      classpath_paths_without_digests = fast_relpath_collection(
        c.path for c in classpath_entries if not c.directory_digest)

      classpath_abs = [c.path for c in classpath_entries]
      classpath_rel = fast_relpath_collection(classpath_abs)

      metacp_inputs = []
      metacp_inputs.extend(classpath_rel)

      counter_val = str(counter()).rjust(counter.format_length(), b' ')
      counter_str = '[{}/{}] '.format(counter_val, counter.size)
      self.context.log.info(
        counter_str,
        'Metacp-ing ',
        items_to_report_element(metacp_inputs, 'jar'),
        ' in ',
        items_to_report_element([t.address.reference() for t in vts.targets], 'target'),
        ' (',
        ctx.target.address.spec,
        ').')

      ctx.ensure_output_dirs_exist()

      tgt, = vts.targets
      with Timer() as timer:
        # Step 1: Convert classpath to SemanticDB
        # ---------------------------------------
        rsc_index_dir = fast_relpath(ctx.rsc_index_dir, get_buildroot())
        args = [
          '--verbose',
          '--stub-broken-signatures',
          '--dependency-classpath', os.pathsep.join(
            metacp_dependencies +
            fast_relpath_collection(self._jvm_lib_jars_abs)
          ),
          # NB: The directory to dump the semanticdb jars generated by metacp.
          '--out', rsc_index_dir,
          os.pathsep.join(metacp_inputs),
        ]

        # NB: If we're building a scala library jar,
        #     also request that metacp generate the indices
        #     for the scala synthetics.
        if self._is_scala_core_library(tgt):
          args = [
            '--include-scala-library-synthetics',
          ] + args
        distribution = self._get_jvm_distribution()

        input_digest = self.context._scheduler.merge_directories(
          tuple(classpath_digests + metacp_dependencies_digests))

        metacp_wu = self._runtool(
          'scala.meta.cli.Metacp',
          'metacp',
          args,
          distribution,
          tgt=tgt,
          input_digest=input_digest,
          input_files=tuple(classpath_paths_without_digests +
                            metacp_dependencies_paths_without_digests),
          output_dir=rsc_index_dir)
        metacp_result = json.loads(stdout_contents(metacp_wu))

        metai_classpath = self._collect_metai_classpath(metacp_result, classpath_rel)

        # Step 1.5: metai Index the semanticdbs
        # -------------------------------------
        self._run_metai_tool(distribution, metai_classpath, rsc_index_dir, tgt)

        abs_output = [(conf, os.path.join(get_buildroot(), x))
                      for conf in self._confs for x in metai_classpath]

        self._metacp_jars_classpath_product.add_for_target(
          ctx.target,
          abs_output,
        )

      self._record_target_stats(tgt,
          len(abs_output),
          len([]),
          timer.elapsed,
          False,
          'metacp'
        )

    rsc_jobs = []
    zinc_jobs = []

    # Invalidated targets are a subset of relevant targets: get the context for this one.
    compile_target = ivts.target
    compile_context_pair = compile_contexts[compile_target]

    # Create the rsc job.
    # Currently, rsc only supports outlining scala.
    if self._only_zinc_compileable(compile_target):
      pass
    elif self._rsc_compilable(compile_target):
      rsc_key = self._rsc_key_for_target(compile_target)
      rsc_jobs.append(
        Job(
          rsc_key,
          functools.partial(
            work_for_vts_rsc,
            ivts,
            compile_context_pair[0]),
          [self._rsc_key_for_target(target) for target in invalid_dependencies] + ['metacp(jdk)'],
          self._size_estimator(compile_context_pair[0].sources),
        )
      )
    elif self._metacpable(compile_target):
      rsc_key = self._rsc_key_for_target(compile_target)
      rsc_jobs.append(
        Job(
          rsc_key,
          functools.partial(
            work_for_vts_rsc_jar_library,
            ivts,
            compile_context_pair[0]),
          [self._rsc_key_for_target(target) for target in invalid_dependencies] + ['metacp(jdk)'],
          self._size_estimator(compile_context_pair[0].sources),
          on_success=ivts.update,
          on_failure=ivts.force_invalidate,
        )
      )
    else:
      raise TaskError("Unexpected target for rsc compile {} with type {}"
        .format(compile_target, type(compile_target)))

    # Create the zinc compile jobs.
    # - Scala zinc compile jobs depend on the results of running rsc on the scala target.
    # - Java zinc compile jobs depend on the zinc compiles of their dependencies, because we can't
    #   generate mjars that make javac happy at this point.

    invalid_dependencies_without_jar_metacps = [t for t in invalid_dependencies
      if not self._metacpable(t)]
    if self._rsc_compilable(compile_target):
      full_key = self._compile_against_rsc_key_for_target(compile_target)
      zinc_jobs.append(
        Job(
          full_key,
          functools.partial(
            self._default_work_for_vts,
            ivts,
            compile_context_pair[1],
            'rsc_classpath',
            counter,
            compile_contexts,
            runtime_classpath_product),
          [
            self._rsc_key_for_target(compile_target)
          ] + [
            self._rsc_key_for_target(target)
            for target in invalid_dependencies_without_jar_metacps
          ] + [
            'metacp(jdk)'
          ],
          self._size_estimator(compile_context_pair[1].sources),
          # NB: right now, only the last job will write to the cache, because we don't
          #     do multiple cache entries per target-task tuple.
          on_success=ivts.update,
          on_failure=ivts.force_invalidate,
        )
      )
    elif self._only_zinc_compileable(compile_target):
      # write to both rsc classpath and runtime classpath
      class CompositeProductAdder(object):
        def __init__(self, runtime_classpath_product, rsc_classpath_product):
          self.rsc_classpath_product = rsc_classpath_product
          self.runtime_classpath_product = runtime_classpath_product

        def add_for_target(self, *args, **kwargs):
          self.runtime_classpath_product.add_for_target(*args, **kwargs)
          self.rsc_classpath_product.add_for_target(*args, **kwargs)

      full_key = self._compile_against_rsc_key_for_target(compile_target)
      zinc_jobs.append(
        Job(
          full_key,
          functools.partial(
            self._default_work_for_vts,
            ivts,
            compile_context_pair[1],
            'runtime_classpath',
            counter,
            compile_contexts,
            CompositeProductAdder(
              runtime_classpath_product,
              self.context.products.get_data('rsc_classpath'))),
          [
            self._compile_against_rsc_key_for_target(target)
            for target in invalid_dependencies_without_jar_metacps],
          self._size_estimator(compile_context_pair[1].sources),
          # NB: right now, only the last job will write to the cache, because we don't
          #     do multiple cache entries per target-task tuple.
          on_success=ivts.update,
          on_failure=ivts.force_invalidate,
        )
      )

    return rsc_jobs + zinc_jobs

  def select_runtime_context(self, ccs):
    return ccs[1]

  def create_compile_context(self, target, target_workdir):
    # workdir layout:
    # rsc/
    #   - index/   -- metacp results
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
    return [
      RscCompileContext(
        target=target,
        analysis_file=None,
        classes_dir=None,
        jar_file=None,
        zinc_args_file=None,
        rsc_mjar_file=os.path.join(rsc_dir, 'm.jar'),
        log_dir=os.path.join(rsc_dir, 'logs'),
        sources=sources,
        rsc_index_dir=os.path.join(rsc_dir, 'index'),
      ),
      CompileContext(
        target=target,
        analysis_file=os.path.join(zinc_dir, 'z.analysis'),
        classes_dir=ClasspathEntry(os.path.join(zinc_dir, 'classes'), None),
        jar_file=ClasspathEntry(os.path.join(zinc_dir, 'z.jar'), None),
        log_dir=os.path.join(zinc_dir, 'logs'),
        zinc_args_file=os.path.join(zinc_dir, 'zinc_args'),
        sources=sources,
      )
    ]

  def _runtool(
    self, main, tool_name, args, distribution, tgt=None, input_files=tuple(), input_digest=None, output_dir=None):
    if self.execution_strategy == self.HERMETIC:
      with self.context.new_workunit(tool_name) as wu:
        tool_classpath_abs = self.tool_classpath(tool_name)
        tool_classpath = fast_relpath_collection(tool_classpath_abs)

        classpath_for_cmd = os.pathsep.join(tool_classpath)
        cmd = [
          distribution.java,
        ]
        cmd.extend(self.get_options().jvm_options)
        cmd.extend(['-cp', classpath_for_cmd])
        cmd.extend([main])
        cmd.extend(args)

        pathglobs = list(tool_classpath)
        pathglobs.extend(f if os.path.isfile(f) else '{}/**'.format(f) for f in input_files)

        if pathglobs:
          root = PathGlobsAndRoot(
          PathGlobs(tuple(pathglobs)),
          text_type(get_buildroot()))
          # dont capture snapshot, if pathglobs is empty
          path_globs_input_digest = self.context._scheduler.capture_snapshots((root,))[0].directory_digest

        if path_globs_input_digest and input_digest:
          epr_input_files = self.context._scheduler.merge_directories(
              (path_globs_input_digest, input_digest))
        else:
          epr_input_files = path_globs_input_digest or input_digest

        epr = ExecuteProcessRequest(
          argv=tuple(cmd),
          input_files=epr_input_files,
          output_files=tuple(),
          output_directories=(output_dir,),
          timeout_seconds=15*60,
          description='run {} for {}'.format(tool_name, tgt),
          # TODO: These should always be unicodes
          # Since this is always hermetic, we need to use `underlying_dist`
          jdk_home=text_type(self._zinc.underlying_dist.home),
        )
        res = self.context.execute_process_synchronously_without_raising(
          epr,
          self.name(),
          [WorkUnitLabel.TOOL])

        if res.exit_code != 0:
          raise TaskError(res.stderr)

        if output_dir:
          dump_digest(output_dir, res.output_directory_digest)
          self.context._scheduler.materialize_directories((
            DirectoryToMaterialize(
              # NB the first element here is the root to materialize into, not the dir to snapshot
              text_type(get_buildroot()),
              res.output_directory_digest),
          ))
          # TODO drop a file containing the digest, named maybe output_dir.digest
        return res
    else:
      with self.context.new_workunit(tool_name) as wu:
        result = self.runjava(classpath=self.tool_classpath(tool_name),
                              main=main,
                              jvm_options=self.get_options().jvm_options,
                              args=args,
                              workunit_name=tool_name,
                              workunit_labels=[WorkUnitLabel.TOOL],
                              dist=distribution
        )
        if result != 0:
          raise TaskError('Running {} failed'.format(tool_name))
        runjava_wu = None
        for c in wu.children:
          if c.name is tool_name:
            runjava_wu = c
            break
        if runjava_wu is None:
          raise Exception('couldnt find work unit for underlying execution')
        return runjava_wu

  def _run_metai_tool(self,
                      distribution,
                      metai_classpath,
                      rsc_index_dir,
                      tgt,
                      extra_input_files=()):
    # TODO have metai write to a different spot than metacp
    # Currently, the metai step depends on the fact that materializing
    # ignores existing files. It should write the files to a different
    # location, either by providing inputs from a different location,
    # or invoking a script that does the copying
    args = [
      '--verbose',
      os.pathsep.join(metai_classpath)
    ]
    self._runtool(
      'scala.meta.cli.Metai',
      'metai',
      args,
      distribution,
      tgt=tgt,
      input_files=tuple(metai_classpath) + tuple(extra_input_files),
      output_dir=rsc_index_dir
    )

  def _collect_metai_classpath(self, metacp_result, relative_input_paths):
    metai_classpath = []

    relative_workdir = fast_relpath(
      self.context.options.for_global_scope().pants_workdir,
      get_buildroot())
    # NB The json uses absolute paths pointing into either the buildroot or
    #    the temp directory of the hermetic build. This relativizes the keys.
    #    TODO remove this after https://github.com/scalameta/scalameta/issues/1791 is released
    desandboxify = _create_desandboxify_fn(
      [
        os.path.join(relative_workdir, 'resolve', 'coursier', '[^/]*', 'cache', '.*'),
        os.path.join(relative_workdir, 'resolve', 'ivy', '[^/]*', 'ivy', 'jars', '.*'),
        os.path.join(relative_workdir, 'compile', 'rsc', '.*'),
        os.path.join(relative_workdir, '\.jdk', '.*'),
        os.path.join('\.jdk', '.*'),
      ]
      )

    status_elements = {
      desandboxify(k): desandboxify(v)
      for k,v in metacp_result["status"].items()
    }

    for cp_entry in relative_input_paths:
      metai_classpath.append(status_elements[cp_entry])

    scala_lib_synthetics = metacp_result["scalaLibrarySynthetics"]
    if scala_lib_synthetics:
      metai_classpath.append(desandboxify(scala_lib_synthetics))

    return metai_classpath

  def _get_jvm_distribution(self):
    # TODO We may want to use different jvm distributions depending on what
    # java version the target expects to be compiled against.
    # See: https://github.com/pantsbuild/pants/issues/6416 for covering using
    #      different jdks in remote builds.
    local_distribution = JvmPlatform.preferred_jvm_distribution([], strict=True)
    if self.execution_strategy == self.HERMETIC and self.get_options().remote_execution_server:
      class HermeticDistribution(object):
        def __init__(self, home_path, distribution):
          self._underlying = distribution
          self._home = home_path

        def find_libs(self, names):
          underlying_libs = self._underlying.find_libs(names)
          return [self._rehome(l) for l in underlying_libs]

        @property
        def java(self):
          return os.path.join(self._home, 'bin', 'java')

        def _rehome(self, l):
          return os.path.join(self._home, l[len(self._underlying.home)+1:])

      return HermeticDistribution('.jdk', local_distribution)
    else:
      return local_distribution
