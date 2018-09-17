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
from pants.backend.jvm.tasks.jvm_compile.compile_context import CompileContext
from pants.backend.jvm.tasks.jvm_compile.execution_graph import Job
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.engine.fs import DirectoryToMaterialize, PathGlobs, PathGlobsAndRoot
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.java.jar.jar_dependency import JarDependency
from pants.util.contextutil import Timer
from pants.util.dirutil import fast_relpath, safe_mkdir


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
  return [fast_relpath(c, buildroot) for c in collection]


def stdout_contents(wu):
  if isinstance(wu, FallibleExecuteProcessResult):
    return wu.stdout.rstrip()
  with open(wu.output_paths()['stdout']) as f:
    return f.read().rstrip()


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
               index_dir,
               outline_dir):
    super(RscCompileContext, self).__init__(target, analysis_file, classes_dir, jar_file,
                                               log_dir, zinc_args_file, sources)
    self.rsc_mjar_file = rsc_mjar_file
    self.index_dir = index_dir
    self.outline_dir = outline_dir

  def ensure_output_dirs_exist(self):
    safe_mkdir(os.path.dirname(self.rsc_mjar_file))
    safe_mkdir(self.index_dir)
    safe_mkdir(self.outline_dir)


class RscCompile(ZincCompile):
  """Compile Scala and Java code to classfiles using Rsc."""

  _name = 'rsc' # noqa
  compiler_name = 'rsc'

  @classmethod
  def implementation_version(cls):
    return super(RscCompile, cls).implementation_version() + [('RscCompile', 7)]

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
    for target in targets:
      rsc_cc, compile_cc = compile_contexts[target]
      if target.has_sources('.java'):
        self.context.products.get_data('rsc_classpath').add_for_target(
          compile_cc.target,
          [(conf, compile_cc.jar_file) for conf in self._confs])
      elif target.has_sources('.scala'):
        pass
      else:
        pass

  def create_empty_extra_products(self):
    super(RscCompile, self).create_empty_extra_products()

    compile_classpath = self.context.products.get_data('compile_classpath')
    classpath_product = self.context.products.get_data('rsc_classpath')
    if not classpath_product:
      self.context.products.get_data('rsc_classpath', compile_classpath.copy)
    else:
      classpath_product.update(compile_classpath)

  def _rsc_key_for_target(self, compile_target):
    if compile_target.has_sources('.java'):
      # rsc outlining with java dependencies depend on the java's zinc compile
      return self._compile_against_rsc_key_for_target(compile_target)
    elif compile_target.has_sources('.scala'):
      return "rsc({})".format(compile_target.address.spec)
    else:
      raise TaskError('unexpected target for compiling with rsc_outline .... {}'.format(compile_target))

  def _compile_against_rsc_key_for_target(self, compile_target):
    return "compile_against_rsc({})".format(compile_target.address.spec)

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

      if not hit_cache:
        cp_entries = []

        # Include the current machine's jdk lib jars. This'll blow up remotely.
        # We need a solution for that.
        # Probably something to do with https://github.com/pantsbuild/pants/pull/6346
        distribution = JvmPlatform.preferred_jvm_distribution([ctx.target.platform], strict=True)
        jvm_lib_jars_abs = distribution.find_libs(['rt.jar', 'dt.jar', 'jce.jar', 'tools.jar'])
        cp_entries.extend(jvm_lib_jars_abs)

        classpath_abs = self._zinc.compile_classpath(
          'rsc_classpath',
          ctx.target,
          extra_cp_entries=self._extra_compile_time_classpath)
        classpath_rel = fast_relpath_collection(classpath_abs)
        cp_entries.extend(classpath_rel)

        ctx.ensure_output_dirs_exist()
        
        tgt, = vts.targets
        with Timer() as timer:
          # Step 1: Convert classpath to SemanticDB
          # ---------------------------------------
          scalac_classpath_path_entries_abs = self.tool_classpath('workaround-metacp-dependency-classpath')
          scalac_classpath_path_entries = fast_relpath_collection(scalac_classpath_path_entries_abs)
          index_dir = fast_relpath(ctx.index_dir, get_buildroot())
          args = [
            '--verbose',
            # NB: Without this setting, rsc will be missing some symbols
            #     from the scala library.
            '--include-scala-library-synthetics', # TODO generate these once and cache them
            # NB: We need to add these extra dependencies in order to be able
            #     to find symbols used by the scalac jars.
            '--dependency-classpath', os.pathsep.join(scalac_classpath_path_entries),
            # NB: The directory to dump the semanticdb jars generated by metacp.
            # TODO: break this out into a separate job so that we can apply
            #       it once per 3rdparty target.
            '--out', index_dir,
            os.pathsep.join(cp_entries),
          ]
          metacp_wu = self._runtool(
            'scala.meta.cli.Metacp',
            'metacp',
            args,
            distribution,
            tgt=tgt,
            input_files=(scalac_classpath_path_entries + classpath_rel),
            output_dir=index_dir)
          metacp_stdout = stdout_contents(metacp_wu)
          metacp_result = json.loads(metacp_stdout)
          metai_classpath = []
          
          def desandboxify_pantsd_loc(path):
            # TODO come up with a cleaner way to maybe relpath paths.
            try:
              path = fast_relpath(path, get_buildroot())
            except Exception:
              pass
            pattern = 'process-execution[^{}]+/'.format(re.escape(os.path.sep))
            return re.split(pattern, path)[-1]

          # TODO when these are generated once, we won't need to collect them here.  
          metai_classpath.append(desandboxify_pantsd_loc(metacp_result["scalaLibrarySynthetics"]))
          # NB The json is absolute pathed pointing into either the buildroot or
          #    the temp directory of the hermetic build. This relativizes the keys.
          status_elements = {
            desandboxify_pantsd_loc(k): v
            for k,v in metacp_result["status"].items()
          }

          for cp_entry in classpath_rel:
            metai_classpath.append(desandboxify_pantsd_loc(status_elements[cp_entry]))
          for cp_entry in jvm_lib_jars_abs:
            metai_classpath.append(desandboxify_pantsd_loc(status_elements[cp_entry]))

          # Step 1.5: metai Index the semanticdbs
          # -------------------------------------
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
            input_files=metai_classpath,
            output_dir=index_dir
          )

          # Step 2: Outline Scala sources into SemanticDB
          # ---------------------------------------------
          outline_dir = fast_relpath(ctx.outline_dir, get_buildroot())
          rsc_out = os.path.join(outline_dir, 'META-INF/semanticdb/out.semanticdb')
          safe_mkdir(os.path.join(outline_dir, 'META-INF/semanticdb'))
          target_sources = ctx.sources
          args = [
            '-cp', os.pathsep.join(metai_classpath),
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
            input_files=target_sources + metai_classpath,
            output_dir=outline_dir)
          rsc_classpath = [outline_dir]

          # Step 2.5: Postprocess the rsc outputs
          # TODO: This is only necessary as a workaround for https://github.com/twitter/rsc/issues/199.
          # Ideally, Rsc would do this on its own.
          args = [
            '--verbose',
            os.pathsep.join(rsc_classpath)
          ]
          self._runtool(
            'scala.meta.cli.Metai',
            'metai',
            args,
            distribution,
            tgt=tgt,
            input_files=[rsc_out],
            output_dir=outline_dir
          )

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
            input_files=[
              rsc_out,
              os.path.join(outline_dir, 'META-INF', 'semanticdb.semanticdbx')
            ],
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

    rsc_jobs = []
    zinc_jobs = []

    # Invalidated targets are a subset of relevant targets: get the context for this one.
    compile_target = ivts.target
    compile_context_pair = compile_contexts[compile_target]

    # Create the rsc_outline job.
    # Currently, rsc_outline only supports outlining scala.
    if compile_target.has_sources('.java'):
      pass
    elif compile_target.has_sources('.scala'):
      rsc_key = self._rsc_key_for_target(compile_target)
      rsc_jobs.append(
        Job(
          rsc_key,
          functools.partial(
            work_for_vts_rsc,
            ivts,
            compile_context_pair[0]),
          [self._rsc_key_for_target(target) for target in invalid_dependencies],
          self._size_estimator(compile_context_pair[0].sources),
        )
      )

    # Create the zinc compile jobs.
    # - Scala zinc compile jobs depend on the results of running rsc_outline on the scala target.
    # - Java zinc compile jobs depend on the zinc compiles of their dependencies, because we can't
    #   generate mjars that make javac happy at this point.
    if compile_target.has_sources('.scala'):
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
          [self._rsc_key_for_target(compile_target)] + [self._rsc_key_for_target(target)
                                                           for target in invalid_dependencies],
          self._size_estimator(compile_context_pair[1].sources),
          # NB: right now, only the last job will write to the cache, because we don't
          #     do multiple cache entries per target-task tuple.
          on_success=ivts.update,
          on_failure=ivts.force_invalidate,
        )
      )
    elif compile_target.has_sources('.java'):
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
          [self._compile_against_rsc_key_for_target(target) for target in invalid_dependencies],
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
        index_dir=os.path.join(rsc_dir, 'index'),
        outline_dir=os.path.join(rsc_dir, 'outline'),
      ),
      CompileContext(
        target=target,
        analysis_file=os.path.join(zinc_dir, 'z.analysis'),
        classes_dir=os.path.join(zinc_dir, 'classes'),
        jar_file=os.path.join(zinc_dir, 'z.jar'),
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
          env=dict(),
          input_files=input_files_directory_digest,
          output_files=tuple(),
          output_directories=(output_dir,),
          timeout_seconds=15*60,
          description='run {} for {}'.format(tool_name, tgt)
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
                              workunit_labels=[WorkUnitLabel.TOOL])
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
