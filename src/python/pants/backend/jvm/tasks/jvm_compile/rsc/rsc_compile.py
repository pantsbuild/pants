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
from pants.engine.fs import DirectoryToMaterialize, PathGlobs, PathGlobsAndRoot
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.java.jar.jar_dependency import JarDependency
from pants.reporting.reporting_utils import items_to_report_element
from pants.util.contextutil import Timer
from pants.util.dirutil import fast_relpath, fast_relpath_optional, safe_mkdir


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
  regexes = [re.compile(p) for p in possible_path_patterns]
  def desandboxify(path):
    if not path:
      return path
    for r in regexes:
      match = r.search(path)
      print('>>> matched {} with {} against {}'.format(match, r.pattern, path))
      if match:
        return match.group(0)
    return path
  return desandboxify


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
               rsc_index_dir,
               rsc_outline_dir):
    super(RscCompileContext, self).__init__(target, analysis_file, classes_dir, jar_file,
                                               log_dir, zinc_args_file, sources)
    self.rsc_mjar_file = rsc_mjar_file
    self.rsc_index_dir = rsc_index_dir
    self.rsc_outline_dir = rsc_outline_dir

  def ensure_output_dirs_exist(self):
    safe_mkdir(os.path.dirname(self.rsc_mjar_file))
    safe_mkdir(self.rsc_index_dir)
    safe_mkdir(self.rsc_outline_dir)


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

    rsc_toolchain_version = '0.0.0-294-d7114447'
    scalameta_toolchain_version = '4.0.0-M10'

    # TODO: it would be better to have a less adhoc approach to handling
    #       optional dependencies. See: https://github.com/pantsbuild/pants/issues/6390
    cls.register_jvm_tool(
      register,
      'workaround-metacp-dependency-classpath',
      classpath=[
        JarDependency(org = 'org.scala-lang', name = 'scala-compiler', rev = '2.11.12'),
        JarDependency(org = 'org.scala-lang', name = 'scala-library', rev = '2.11.12'),
        JarDependency(org = 'org.scala-lang', name = 'scala-reflect', rev = '2.11.12'),
        JarDependency(org = 'org.scala-lang.modules', name = 'scala-partest_2.11', rev = '1.0.18'),
        JarDependency(org = 'jline', name = 'jline', rev = '2.14.6'),
        JarDependency(org = 'org.apache.commons', name = 'commons-lang3', rev = '3.3.2'),
        JarDependency(org = 'org.apache.ant', name = 'ant', rev = '1.8.2'),
        JarDependency(org = 'org.pegdown', name = 'pegdown', rev = '1.4.2'),
        JarDependency(org = 'org.testng', name = 'testng', rev = '6.8.7'),
        JarDependency(org = 'org.scalacheck', name = 'scalacheck_2.11', rev = '1.13.1'),
        JarDependency(org = 'org.jmock', name = 'jmock-legacy', rev = '2.5.1'),
        JarDependency(org = 'org.easymock', name = 'easymockclassextension', rev = '3.1'),
        JarDependency(org = 'org.seleniumhq.selenium', name = 'selenium-java', rev = '2.35.0'),
      ],
      custom_rules=[
        Shader.exclude_package('*', recursive=True),]
    )
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
      'mjar',
      classpath=[
          JarDependency(
              org='com.twitter',
              name='mjar_2.11',
              rev=rsc_toolchain_version,
          ),
      ],
      custom_rules=[
        Shader.exclude_package('scala', recursive=True),
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
    # TODO when digests are added, if the target is valid,
    # the digest should be loaded in from the cc somehow.
    # See: #6504
    for target in targets:
      rsc_cc, compile_cc = compile_contexts[target]
      if self._only_zinc_compileable(target):
        self.context.products.get_data('rsc_classpath').add_for_target(
          compile_cc.target,
          [(conf, compile_cc.jar_file) for conf in self._confs])
      elif self._rsc_compilable(target):
        self.context.products.get_data('rsc_classpath').add_for_target(
          rsc_cc.target,
          [(conf, rsc_cc.rsc_mjar_file) for conf in self._confs])
      elif self._metacpable(target):
        # Walk the metacp results dir and add classpath entries for all the files there.
        # TODO exercise this with a test.
        for root, dirs, files in os.walk(rsc_cc.rsc_index_dir):
          self.context.products.get_data('rsc_classpath').add_for_target(
            rsc_cc.target,
            [(conf, os.path.join(root, f)) for conf in self._confs for f in files]
          )
      else:
        pass

  def _metacpable(self, target):
    return isinstance(target, JarLibrary)

  def _rsc_compilable(self, target):
    return target.has_sources('.scala')

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
    index_dir = os.path.join(self.workdir, '--jdk--', 'index')

    def work_for_vts_rsc_jdk():
      distribution = self._get_jvm_distribution()
      jvm_lib_jars_abs = distribution.find_libs(['rt.jar', 'dt.jar', 'jce.jar', 'tools.jar'])
      self._jvm_lib_jars_abs = jvm_lib_jars_abs

      cp_entries = tuple(jvm_lib_jars_abs)

      counter_val = str(counter()).rjust(counter.format_length(), b' ')
      counter_str = '[{}/{}] '.format(counter_val, counter.size)
      self.context.log.info(
        counter_str,
        'Metacp-ing ',
        items_to_report_element(cp_entries, 'jar'),
        ' in the jdk')

      safe_mkdir(index_dir)

      with Timer() as timer:
        # Step 1: Convert classpath to SemanticDB
        # ---------------------------------------
        rsc_index_dir = fast_relpath(index_dir, get_buildroot())
        args = [
          '--verbose',
          # NB: The directory to dump the semanticdb jars generated by metacp.
          '--out', rsc_index_dir,
          os.pathsep.join(cp_entries),
        ]
        metacp_wu = self._runtool(
          'scala.meta.cli.Metacp',
          'metacp',
          args,
          distribution,
          tgt='jdk',
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
        self._run_metai_tool(distribution, metai_classpath, rsc_index_dir, tgt='jdk')

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

      if not hit_cache:
        cp_entries = []

        distribution = self._get_jvm_distribution()

        classpath_abs = self._zinc.compile_classpath(
          'rsc_classpath',
          ctx.target,
          extra_cp_entries=self._extra_compile_time_classpath)

        jar_deps = [t for t in DependencyContext.global_instance().dependencies_respecting_strict_deps(target)
                    if isinstance(t, JarLibrary)]
        metacp_jar_classpath_abs = [y[1] for y in self._metacp_jars_classpath_product.get_for_targets(
          jar_deps
        )]
        metacp_jar_classpath_abs.extend(self._jvm_lib_metacp_classpath)
        jar_jar_paths = {y[1] for y in self.context.products.get_data('rsc_classpath').get_for_targets(jar_deps)}

        classpath_abs = [c for c in classpath_abs if c not in jar_jar_paths]


        classpath_rel = fast_relpath_collection(classpath_abs)
        metacp_jar_classpath_rel = fast_relpath_collection(metacp_jar_classpath_abs)
        cp_entries.extend(classpath_rel)

        ctx.ensure_output_dirs_exist()

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

        tgt, = vts.targets
        with Timer() as timer:
          if cp_entries:
            # Step 1: Convert classpath to SemanticDB
            # ---------------------------------------
            scalac_classpath_path_entries_abs = self.tool_classpath('workaround-metacp-dependency-classpath')
            scalac_classpath_path_entries = fast_relpath_collection(scalac_classpath_path_entries_abs)
            rsc_index_dir = fast_relpath(ctx.rsc_index_dir, get_buildroot())
            args = [
              '--verbose',
              # NB: We need to add these extra dependencies in order to be able
              #     to find symbols used by the scalac jars.
              '--dependency-classpath', os.pathsep.join(scalac_classpath_path_entries + list(jar_jar_paths) + self._jvm_lib_jars_abs),
              # NB: The directory to dump the semanticdb jars generated by metacp.
              '--out', rsc_index_dir,
              os.pathsep.join(cp_entries),
            ]
            metacp_wu = self._runtool(
              'scala.meta.cli.Metacp',
              'metacp',
              args,
              distribution,
              tgt=tgt,
              input_files=tuple(scalac_classpath_path_entries + classpath_rel),
              output_dir=rsc_index_dir)
            metacp_stdout = stdout_contents(metacp_wu)
            metacp_result = json.loads(metacp_stdout)

            metai_classpath = self._collect_metai_classpath(metacp_result, classpath_rel)

            # Step 1.5: metai Index the semanticdbs
            # -------------------------------------
            self._run_metai_tool(distribution, metai_classpath, rsc_index_dir, tgt)
          else:
            # NB: there are no unmetacp'd dependencies
            metai_classpath = []

          # Step 2: Outline Scala sources into SemanticDB
          # ---------------------------------------------
          rsc_outline_dir = fast_relpath(ctx.rsc_outline_dir, get_buildroot())
          rsc_out = os.path.join(rsc_outline_dir, 'META-INF/semanticdb/out.semanticdb')
          safe_mkdir(os.path.join(rsc_outline_dir, 'META-INF/semanticdb'))
          target_sources = ctx.sources
          args = [
            '-cp', os.pathsep.join(metai_classpath + metacp_jar_classpath_rel),
            '-out', rsc_out,
          ] + target_sources
          self._runtool(
            'rsc.cli.Main',
            'rsc',
            args,
            distribution,
            tgt=tgt,
            # TODO pass the input files from the target snapshot instead of the below
            # input_snapshot = ctx.target.sources_snapshot(scheduler=self.context._scheduler)
            input_files=target_sources + metai_classpath + metacp_jar_classpath_rel,
            output_dir=rsc_outline_dir)
          rsc_classpath = [rsc_outline_dir]

          # Step 2.5: Postprocess the rsc outputs
          # TODO: This is only necessary as a workaround for https://github.com/twitter/rsc/issues/199.
          # Ideally, Rsc would do this on its own.
          self._run_metai_tool(distribution,
            rsc_classpath,
            rsc_outline_dir,
            tgt,
            extra_input_files=(rsc_out,))


          # Step 3: Convert SemanticDB into an mjar
          # ---------------------------------------
          rsc_mjar_file = fast_relpath(ctx.rsc_mjar_file, get_buildroot())
          args = [
            '-out', rsc_mjar_file,
            os.pathsep.join(rsc_classpath),
          ]
          self._runtool(
            'scala.meta.cli.Mjar',
            'mjar',
            args,
            distribution,
            tgt=tgt,
            input_files=(
              rsc_out,
            ),
            output_dir=os.path.dirname(rsc_mjar_file)
            )
          self.context.products.get_data('rsc_classpath').add_for_target(
            ctx.target,
            [(conf, ctx.rsc_mjar_file) for conf in self._confs],
          )

        self._record_target_stats(tgt,
                                  len(cp_entries),
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
      distribution = self._get_jvm_distribution()

      # TODO use compile_classpath
      classpath_abs = [
        path for (conf, path) in
        self.context.products.get_data('rsc_classpath').get_for_target(ctx.target)
      ]

      dependency_classpath = self._zinc.compile_classpath(
        'compile_classpath',
        ctx.target,
        extra_cp_entries=self._extra_compile_time_classpath)
      dependency_classpath = fast_relpath_collection(dependency_classpath)

      classpath_rel = fast_relpath_collection(classpath_abs)

      cp_entries = []
      cp_entries.extend(classpath_rel)

      counter_val = str(counter()).rjust(counter.format_length(), b' ')
      counter_str = '[{}/{}] '.format(counter_val, counter.size)
      self.context.log.info(
        counter_str,
        'Metacp-ing ',
        items_to_report_element(cp_entries, 'jar'),
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
        scalac_classpath_path_entries_abs = self.tool_classpath('workaround-metacp-dependency-classpath')
        scalac_classpath_path_entries = fast_relpath_collection(scalac_classpath_path_entries_abs)
        rsc_index_dir = fast_relpath(ctx.rsc_index_dir, get_buildroot())
        args = [
          '--verbose',
          # NB: We need to add these extra dependencies in order to be able
          #     to find symbols used by the scalac jars.
          '--dependency-classpath', os.pathsep.join(
            dependency_classpath +
            scalac_classpath_path_entries +
            fast_relpath_collection(self._jvm_lib_jars_abs)
          ),
          # NB: The directory to dump the semanticdb jars generated by metacp.
          '--out', rsc_index_dir,
          os.pathsep.join(cp_entries),
        ]

        # NB: If we're building a scala library jar,
        #     also request that metacp generate the indices
        #     for the scala synthetics.
        if self._is_scala_core_library(tgt):
          args = [
            '--include-scala-library-synthetics',
          ] + args
        metacp_wu = self._runtool(
          'scala.meta.cli.Metacp',
          'metacp',
          args,
          distribution,
          tgt=tgt,
          input_files=tuple(dependency_classpath + scalac_classpath_path_entries + classpath_rel),
          output_dir=rsc_index_dir)
        metacp_stdout = stdout_contents(metacp_wu)
        metacp_result = json.loads(metacp_stdout)

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
        rsc_outline_dir=os.path.join(rsc_dir, 'outline'),
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

  def _runtool(self, main, tool_name, args, distribution, tgt=None, input_files=tuple(), output_dir=None):
    if self.execution_strategy == self.HERMETIC:
      # TODO: accept input_digests as well as files.
      with self.context.new_workunit(tool_name) as wu:
        tool_classpath_abs = self.tool_classpath(tool_name)
        tool_classpath = fast_relpath_collection(tool_classpath_abs)

        pathglobs = list(tool_classpath)
        pathglobs.extend(input_files)
        root = PathGlobsAndRoot(
          PathGlobs(tuple(pathglobs)),
          text_type(get_buildroot()))

        tool_snapshots = self.context._scheduler.capture_snapshots((root,))
        input_files_directory_digest = tool_snapshots[0].directory_digest
        classpath_for_cmd = os.pathsep.join(tool_classpath)
        cmd = [
          distribution.java,
        ]
        cmd.extend(self.get_options().jvm_options)
        cmd.extend(['-cp', classpath_for_cmd])
        cmd.extend([main])
        cmd.extend(args)

        epr = ExecuteProcessRequest(
          argv=tuple(cmd),
          input_files=input_files_directory_digest,
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
        os.path.join(relative_workdir, 'resolve', 'ivy', '[^/]*', 'ivy', 'jars', '.*'),
        os.path.join(relative_workdir, 'compile', 'rsc', '.*'),
        os.path.join(relative_workdir, '\.jdk', '.*'),
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
