# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import json
import logging
import os
import re
import textwrap
import zipfile
from collections import defaultdict
from contextlib import closing
from xml.etree import ElementTree

from pants.backend.jvm.subsystems.dependency_context import DependencyContext
from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.zinc import Zinc
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scalac_plugin import ScalacPlugin
from pants.backend.jvm.tasks.classpath_entry import ClasspathEntry
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.hash_utils import hash_file
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.resources import Resources
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    DirectoryToMaterialize,
    PathGlobs,
    PathGlobsAndRoot,
)
from pants.engine.isolated_process import Process
from pants.util.contextutil import open_zip
from pants.util.dirutil import fast_relpath
from pants.util.enums import match
from pants.util.logging import LogLevel
from pants.util.memo import memoized_method, memoized_property
from pants.util.meta import classproperty
from pants.util.strutil import safe_shlex_join

# Well known metadata file required to register scalac plugins with nsc.
_SCALAC_PLUGIN_INFO_FILE = "scalac-plugin.xml"


logger = logging.getLogger(__name__)


class BaseZincCompile(JvmCompile):
    """An abstract base class for zinc compilation tasks."""

    _name = "zinc"

    @staticmethod
    def validate_arguments(log, whitelisted_args, args):
        """Validate that all arguments match whitelisted regexes."""
        valid_patterns = {re.compile(p): v for p, v in whitelisted_args.items()}

        def validate(idx):
            arg = args[idx]
            for pattern, has_argument in valid_patterns.items():
                if pattern.match(arg):
                    return 2 if has_argument else 1
            log.warn(f"Zinc argument '{arg}' is not supported, and is subject to change/removal!")
            return 1

        arg_index = 0
        while arg_index < len(args):
            arg_index += validate(arg_index)

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
            "-C-source",
            f"-C{settings.source_level}",
            "-C-target",
            f"-C{settings.target_level}",
        ]
        if settings.args:
            settings_args = settings.args
            if any("$JAVA_HOME" in a for a in settings.args):
                logger.debug(
                    'Substituting "$JAVA_HOME" with "{}" in jvm-platform args.'.format(
                        distribution.home
                    )
                )
                settings_args = (a.replace("$JAVA_HOME", distribution.home) for a in settings.args)
            zinc_args.extend(settings_args)
        return zinc_args

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("BaseZincCompile", 8)]

    @classmethod
    def get_jvm_options_default(cls, bootstrap_option_values):
        return (
            "-Dfile.encoding=UTF-8",
            "-Dzinc.analysis.cache.limit=1000",
            "-Djava.awt.headless=true",
            "-Xmx2g",
        )

    @classmethod
    def get_args_default(cls, bootstrap_option_values):
        return ("-C-encoding", "-CUTF-8", "-S-encoding", "-SUTF-8", "-S-g:vars")

    @classmethod
    def get_warning_args_default(cls):
        return (
            "-C-deprecation",
            "-C-Xlint:all",
            "-C-Xlint:-serial",
            "-C-Xlint:-path",
            "-S-deprecation",
            "-S-unchecked",
            "-S-Xlint",
        )

    @classmethod
    def get_no_warning_args_default(cls):
        return (
            "-C-nowarn",
            "-C-Xlint:none",
            "-S-nowarn",
            "-S-Xlint:none",
        )

    @classproperty
    def get_fatal_warnings_enabled_args_default(cls):
        return ("-S-Xfatal-warnings", "-C-Werror")

    @classproperty
    def get_compiler_option_sets_enabled_default_value(cls):
        return {"fatal_warnings": cls.get_fatal_warnings_enabled_args_default}

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--whitelisted-args",
            advanced=True,
            type=dict,
            default={"-S.*": False, "-C.*": False, "-file-filter": True, "-msg-filter": True},
            help="A dict of option regexes that make up pants' supported API for zinc. "
            "Options not listed here are subject to change/removal. The value of the dict "
            "indicates that an option accepts an argument.",
        )

        register(
            "--incremental",
            advanced=True,
            type=bool,
            default=True,
            help="When set, zinc will use sub-target incremental compilation, which dramatically "
            "improves compile performance while changing large targets. When unset, "
            "changed targets will be compiled with an empty output directory, as if after "
            "running clean-all.",
        )

        register(
            "--incremental-caching",
            advanced=True,
            type=bool,
            help="When set, the results of incremental compiles will be written to the cache. "
            "This is unset by default, because it is generally a good precaution to cache "
            "only clean/cold builds.",
        )

        register(
            "--use-barebones-logger",
            advanced=True,
            type=bool,
            default=False,
            help="Use our own implementation of the SBT logger in the Zinc compiler. "
            "This is experimental, but it provides great speedups in native-images of Zinc.",
        )

        register(
            "--report-diagnostic-counts",
            advanced=True,
            type=bool,
            default=False,
            help="Have the Zinc compiler record information on Warnings and Errors. "
            "For each target, send the count of diagnostics of each severity (Hint, Information, "
            "Warning, Error) to the reporting server.",
        )

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (Zinc.Factory, JvmPlatform,)

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        ScalaPlatform.prepare_tools(round_manager)

    @property
    def incremental(self):
        """Zinc implements incremental compilation.

        Setting this property causes the task infrastructure to clone the previous results_dir for a
        target into the new results_dir for a target.
        """
        return self.get_options().incremental

    @property
    def cache_incremental(self):
        """Optionally write the results of incremental compiles to the cache."""
        return self.get_options().incremental_caching

    @memoized_property
    def _zinc(self):
        return Zinc.Factory.global_instance().create(self.context.products, self.execution_strategy)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A directory to contain per-target subdirectories with apt processor info files.
        self._processor_info_dir = os.path.join(self.workdir, "apt-processor-info")

        # Validate zinc options.
        ZincCompile.validate_arguments(
            self.context.log, self.get_options().whitelisted_args, self._args
        )
        if self.execution_strategy == self.ExecutionStrategy.hermetic:
            try:
                fast_relpath(self.get_options().pants_workdir, get_buildroot())
            except ValueError:
                raise TaskError(
                    "Hermetic zinc execution currently requires the workdir to be a child of the buildroot "
                    "but workdir was {} and buildroot was {}".format(
                        self.get_options().pants_workdir, get_buildroot(),
                    )
                )

    def select(self, target):
        raise NotImplementedError()

    def select_source(self, source_file_path):
        raise NotImplementedError()

    def register_extra_products_from_contexts(self, targets, compile_contexts):
        compile_contexts = [self.select_runtime_context(compile_contexts[t]) for t in targets]
        zinc_analysis = self.context.products.get_data("zinc_analysis")
        zinc_args = self.context.products.get_data("zinc_args")

        if zinc_analysis is not None:
            for compile_context in compile_contexts:
                zinc_analysis[compile_context.target] = (
                    compile_context.classes_dir.path,
                    compile_context.jar_file.path,
                    compile_context.analysis_file,
                )

        if zinc_args is not None:
            for compile_context in compile_contexts:
                with open(compile_context.args_file, "r") as fp:
                    args = fp.read().strip().split("\n")
                zinc_args[compile_context.target] = args

    def create_empty_extra_products(self):
        if self.context.products.is_required_data("zinc_analysis"):
            self.context.products.safe_create_data("zinc_analysis", dict)

        if self.context.products.is_required_data("zinc_args"):
            self.context.products.safe_create_data("zinc_args", lambda: defaultdict(list))

    def create_extra_products_for_targets(self, targets):
        if not targets:
            return
        if self.context.products.is_required_data("zinc_args"):
            zinc_args = self.context.products.get_data("zinc_args")
            with self.invalidated(
                targets, invalidate_dependents=False, topological_order=True
            ) as invalidation_check:

                compile_contexts = {
                    vt.target: self.create_compile_context(vt.target, vt.results_dir)
                    for vt in invalidation_check.all_vts
                }
                runtime_compile_contexts = {
                    target: self.select_runtime_context(cc)
                    for target, cc in compile_contexts.items()
                }
                for vt in invalidation_check.all_vts:
                    dependency_classpath = self._zinc.compile_classpath_entries(
                        "runtime_classpath",
                        vt.target,
                        extra_cp_entries=self._extra_compile_time_classpath,
                    )
                    dep_context = DependencyContext.global_instance()
                    compiler_option_sets = dep_context.defaulted_property(
                        vt.target, "compiler_option_sets"
                    )
                    zinc_file_manager = dep_context.defaulted_property(
                        vt.target, "zinc_file_manager"
                    )
                    ctx = runtime_compile_contexts[vt.target]
                    absolute_classpath = (ctx.classes_dir.path,) + tuple(
                        ce.path for ce in dependency_classpath
                    )
                    upstream_analysis = dict(
                        self._upstream_analysis(compile_contexts, dependency_classpath)
                    )
                    zinc_args[vt.target] = self.create_zinc_args(
                        ctx,
                        self._args,
                        upstream_analysis,
                        absolute_classpath,
                        vt.target.platform,
                        compiler_option_sets,
                        zinc_file_manager,
                        self._get_plugin_map("javac", Java.global_instance(), ctx.target),
                        self._get_plugin_map("scalac", ScalaPlatform.global_instance(), ctx.target),
                    )

    def post_compile_extra_resources(self, compile_context):
        """Send the diagnostic counts to the reporting server."""
        self._pass_diagnostics_to_reporting_server(compile_context)

        """Override `post_compile_extra_resources` to additionally include scalac_plugin info."""
        result = super().post_compile_extra_resources(compile_context)
        target = compile_context.target

        if isinstance(target, ScalacPlugin):
            result[_SCALAC_PLUGIN_INFO_FILE] = textwrap.dedent(
                """
                <plugin>
                  <name>{}</name>
                  <classname>{}</classname>
                </plugin>
                """.format(
                    target.plugin, target.classname
                )
            )

        return result

    def javac_classpath(self):
        # Note that if this classpath is empty then Zinc will automatically use the javac from
        # the JDK it was invoked with.
        return Java.global_javac_classpath(self.context.products)

    def scalac_classpath_entries(self):
        """Returns classpath entries for the scalac classpath."""
        return ScalaPlatform.global_instance().compiler_classpath_entries(self.context.products)

    @staticmethod
    def relative_to_exec_root(path):
        # TODO: Support workdirs not nested under buildroot by path-rewriting.
        return fast_relpath(path, get_buildroot())

    _LOG_LEVEL_TO_ZINC_LOG_LEVEL = {
        LogLevel.DEBUG: "debug",
        LogLevel.INFO: "info",
        LogLevel.WARN: "warn",
        LogLevel.ERROR: "error",
    }

    def create_zinc_log_level_args(self):
        zinc_log_level = self._LOG_LEVEL_TO_ZINC_LOG_LEVEL.get(self.get_options().level)
        return ["-log-level", zinc_log_level] if zinc_log_level is not None else []

    def _diagnostics_out(self, ctx):
        if not self.get_options().report_diagnostic_counts:
            return None
        return self.relative_to_exec_root(ctx.diagnostics_out)

    def create_zinc_args(
        self,
        ctx,
        args,
        upstream_analysis,
        absolute_classpath,
        settings,
        compiler_option_sets,
        zinc_file_manager,
        javac_plugin_map,
        scalac_plugin_map,
    ):
        analysis_cache = self.relative_to_exec_root(ctx.analysis_file)
        classes_dir = self.relative_to_exec_root(ctx.classes_dir.path)
        jar_file = self.relative_to_exec_root(ctx.jar_file.path)
        # TODO: Have these produced correctly, rather than having to relativize them here
        relative_classpath = tuple(self.relative_to_exec_root(c) for c in absolute_classpath)

        # list of classpath entries
        scalac_classpath_entries = self.scalac_classpath_entries()
        scala_path = [
            self.relative_to_exec_root(classpath_entry.path)
            for classpath_entry in scalac_classpath_entries
        ]
        zinc_args = []
        zinc_args.extend(self.create_zinc_log_level_args())
        zinc_args.extend(
            [
                "-analysis-cache",
                analysis_cache,
                "-classpath",
                ":".join(relative_classpath),
                "-d",
                classes_dir,
                "-jar",
                jar_file,
            ]
        )
        diag_out = self._diagnostics_out(ctx)
        if diag_out:
            zinc_args.extend(["-diag", diag_out])

        if not self.get_options().colors:
            zinc_args.append("-no-color")

        if self.post_compile_extra_resources(ctx):
            post_compile_merge_dir = self.relative_to_exec_root(ctx.post_compile_merge_dir)
            zinc_args.extend(["--post-compile-merge-dir", post_compile_merge_dir])

        if self.get_options().use_barebones_logger:
            zinc_args.append("--use-barebones-logger")

        compiler_bridge_classpath_entry = self._zinc.compile_compiler_bridge(self.context)
        zinc_args.extend(
            [
                "-compiled-bridge-jar",
                self.relative_to_exec_root(compiler_bridge_classpath_entry.path),
            ]
        )
        zinc_args.extend(["-scala-path", ":".join(scala_path)])

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
            set(absolute_classpath) | set(self.scalac_plugin_classpath_elements())
        ) - {ctx.classes_dir.path, ctx.jar_file.path}
        zinc_args.extend(
            self._scalac_plugin_args(scalac_plugin_map, scalac_plugin_search_classpath)
        )
        if upstream_analysis:
            zinc_args.extend(
                [
                    "-analysis-map",
                    ",".join(
                        "{}:{}".format(self.relative_to_exec_root(k), self.relative_to_exec_root(v))
                        for k, v in upstream_analysis.items()
                    ),
                ]
            )

        zinc_args.extend(args)
        zinc_args.extend(self._get_zinc_arguments(settings))
        zinc_args.append("-transactional")

        compiler_option_sets_args = self.get_merged_args_for_compiler_option_sets(
            compiler_option_sets
        )

        # Needed to make scoverage CodeGrid highlighting work
        if "scoverage" in scalac_plugin_map.keys():
            compiler_option_sets_args += ["-S-Yrangepos"]

        zinc_args.extend(compiler_option_sets_args)

        if not self._clear_invalid_analysis:
            zinc_args.append("-no-clear-invalid-analysis")

        if not zinc_file_manager:
            zinc_args.append("-no-zinc-file-manager")

        zinc_args.extend(ctx.sources)
        return zinc_args

    def compile(
        self,
        ctx,
        args,
        dependency_classpath,
        upstream_analysis,
        settings,
        compiler_option_sets,
        zinc_file_manager,
        javac_plugin_map,
        scalac_plugin_map,
    ):
        absolute_classpath = (ctx.classes_dir.path,) + tuple(ce.path for ce in dependency_classpath)

        if self.get_options().capture_classpath:
            self._record_compile_classpath(absolute_classpath, ctx.target, ctx.classes_dir.path)

        self._verify_zinc_classpath(
            absolute_classpath,
            allow_dist=(self.execution_strategy != self.ExecutionStrategy.hermetic),
        )
        # TODO: Investigate upstream_analysis for hermetic compiles
        self._verify_zinc_classpath(upstream_analysis.keys())

        zinc_args = self.create_zinc_args(
            ctx,
            args,
            upstream_analysis,
            absolute_classpath,
            settings,
            compiler_option_sets,
            zinc_file_manager,
            javac_plugin_map,
            scalac_plugin_map,
        )

        classes_dir = self.relative_to_exec_root(ctx.classes_dir.path)
        jar_file = self.relative_to_exec_root(ctx.jar_file.path)
        compiler_bridge_classpath_entry = self._zinc.compile_compiler_bridge(self.context)
        # list of classpath entries
        scalac_classpath_entries = self.scalac_classpath_entries()

        jvm_options = []
        if self.javac_classpath():
            # Make the custom javac classpath the first thing on the bootclasspath, to ensure that
            # it's the one javax.tools.ToolProvider.getSystemJavaCompiler() loads.
            # It will probably be loaded even on the regular classpath: If not found on the bootclasspath,
            # getSystemJavaCompiler() constructs a classloader that loads from the JDK's tools.jar.
            # That classloader will first delegate to its parent classloader, which will search the
            # regular classpath.  However it's harder to guarantee that our javac will precede any others
            # on the classpath, so it's safer to prefix it to the bootclasspath.
            jvm_options.extend([f"-Xbootclasspath/p:{':'.join(self.javac_classpath())}"])
        jvm_options.extend(self._jvm_options)

        self.log_zinc_file(ctx.analysis_file)
        self.write_argsfile(ctx, zinc_args)

        return match(
            self.execution_strategy,
            {
                self.ExecutionStrategy.hermetic: lambda: self._compile_hermetic(
                    jvm_options,
                    ctx,
                    classes_dir,
                    jar_file,
                    compiler_bridge_classpath_entry,
                    dependency_classpath,
                    scalac_classpath_entries,
                ),
                self.ExecutionStrategy.subprocess: lambda: self._compile_nonhermetic(
                    jvm_options, ctx, classes_dir
                ),
                self.ExecutionStrategy.nailgun: lambda: self._compile_nonhermetic(
                    jvm_options, ctx, classes_dir
                ),
            },
        )()

    def record_extra_target_stats(self, ctx):
        self._pass_diagnostics_to_reporting_server(ctx)

    def _aggregate_diagnostics(self, lsp_data):
        # Note: this is not arbitrary. It is exactly every value that the LSP's DiagnosticSeverity allows.
        # See https://microsoft.github.io/language-server-protocol/specification#diagnostic
        counts = {
            "Error": 0,
            "Warning": 0,
            "Information": 0,
            "Hint": 0,
        }
        for published_diagnostics in lsp_data:
            for diagnostic in published_diagnostics["diagnostics"]:
                severity = diagnostic["severity"]
                counts[severity] += 1
        return counts

    def _pass_diagnostics_to_reporting_server(self, ctx):
        diagnostics_file = self._diagnostics_out(ctx)
        if not (diagnostics_file and os.path.exists(diagnostics_file)):
            return
        with open(diagnostics_file) as json_diagnostics:
            data = json.load(json_diagnostics)
            counts = self._aggregate_diagnostics(data)
            self.context.log.info(f"Reporting number of diagnostics for: {ctx.target.address}")
            for (severity, count) in counts.items():
                self.context.log.info(f"    {severity}: {count}")
                self.context.run_tracker.report_target_info(
                    self.options_scope, ctx.target, ["diagnostic_counts", severity], count
                )

    class ZincCompileError(TaskError):
        """An exception type specifically to signal a failed zinc execution."""

    def _compile_nonhermetic(self, jvm_options, ctx, classes_directory):
        # Populate the resources to merge post compile onto disk for the nonhermetic case,
        # where `--post-compile-merge-dir` was added is the relevant part.
        self.context._scheduler.materialize_directory(
            DirectoryToMaterialize(self.post_compile_extra_resources_digest(ctx)),
        )

        exit_code = self.runjava(
            classpath=self.get_zinc_compiler_classpath(),
            main=Zinc.ZINC_COMPILE_MAIN,
            jvm_options=jvm_options,
            args=[f"@{ctx.args_file}"],
            workunit_name=self.name(),
            workunit_labels=[WorkUnitLabel.COMPILER],
            dist=self._zinc.dist,
        )
        if exit_code != 0:
            raise self.ZincCompileError("Zinc compile failed.", exit_code=exit_code)

    # Snapshot the nailgun-server jar, to use it to start nailguns in the hermetic case.
    # TODO(#8480): Make this jar natively accessible to the engine,
    #              because it will help when moving the JVM pipeline to v2.
    @memoized_method
    def _nailgun_server_classpath_entry(self):
        nailgun_jar = self.tool_jar("nailgun-server")
        (nailgun_jar_snapshot,) = self.context._scheduler.capture_snapshots(
            (
                PathGlobsAndRoot(
                    PathGlobs((fast_relpath(nailgun_jar, get_buildroot()),)), get_buildroot()
                ),
            )
        )
        nailgun_jar_digest = nailgun_jar_snapshot.directory_digest
        return ClasspathEntry(nailgun_jar, nailgun_jar_digest)

    def _compile_hermetic(
        self,
        jvm_options,
        ctx,
        classes_dir,
        jar_file,
        compiler_bridge_classpath_entry,
        dependency_classpath,
        scalac_classpath_entries,
    ):
        zinc_relpath = fast_relpath(self._zinc.zinc.path, get_buildroot())

        snapshots = [
            ctx.target.sources_snapshot(self.context._scheduler),
        ]

        # scala_library() targets with java_sources have circular dependencies on those java source
        # files, and we provide them to the same zinc command line that compiles the scala, so we need
        # to make sure those source files are available in the hermetic execution sandbox.
        java_sources_targets = getattr(ctx.target, "java_sources", [])
        java_sources_snapshots = [
            tgt.sources_snapshot(self.context._scheduler) for tgt in java_sources_targets
        ]
        snapshots.extend(java_sources_snapshots)

        # Ensure the dependencies and compiler bridge jars are available in the execution sandbox.
        relevant_classpath_entries = dependency_classpath + [
            compiler_bridge_classpath_entry,
            self._nailgun_server_classpath_entry(),  # We include nailgun-server, to use it to start servers when needed from the hermetic execution case.
        ]
        directory_digests = [
            entry.directory_digest for entry in relevant_classpath_entries if entry.directory_digest
        ]
        if len(directory_digests) != len(relevant_classpath_entries):
            for dep in relevant_classpath_entries:
                if not dep.directory_digest:
                    raise AssertionError(
                        "ClasspathEntry {} didn't have a Digest, so won't be present for hermetic "
                        "execution of zinc".format(dep)
                    )
        directory_digests.extend(
            classpath_entry.directory_digest for classpath_entry in scalac_classpath_entries
        )

        if self._zinc.use_native_image:
            if jvm_options:
                raise ValueError(
                    "`{}` got non-empty jvm_options when running with a graal native-image, but this is "
                    "unsupported. jvm_options received: {}".format(
                        self.options_scope, safe_shlex_join(jvm_options)
                    )
                )
            native_image_path, native_image_snapshot = self._zinc.native_image(self.context)
            native_image_snapshots = [
                native_image_snapshot.directory_digest,
            ]
            scala_boot_classpath = [
                classpath_entry.path for classpath_entry in scalac_classpath_entries
            ] + [
                # We include rt.jar on the scala boot classpath because the compiler usually gets its
                # contents from the VM it is executing in, but not in the case of a native image. This
                # resolves a `object java.lang.Object in compiler mirror not found.` error.
                ".jdk/jre/lib/rt.jar",
                # The same goes for the jce.jar, which provides javax.crypto.
                ".jdk/jre/lib/jce.jar",
            ]
            image_specific_argv = [
                native_image_path,
                "-java-home",
                ".jdk",
                f"-Dscala.boot.class.path={os.pathsep.join(scala_boot_classpath)}",
                "-Dscala.usejavacp=true",
            ]
        else:
            native_image_snapshots = []
            # TODO: Lean on distribution for the bin/java appending here
            image_specific_argv = (
                [".jdk/bin/java"] + jvm_options + ["-cp", zinc_relpath, Zinc.ZINC_COMPILE_MAIN]
            )

        (argfile_snapshot,) = self.context._scheduler.capture_snapshots(
            [
                PathGlobsAndRoot(
                    PathGlobs([fast_relpath(ctx.args_file, get_buildroot())]), get_buildroot(),
                ),
            ]
        )

        relpath_to_analysis = fast_relpath(ctx.analysis_file, get_buildroot())
        merged_local_only_scratch_inputs = self._compute_local_only_inputs(
            classes_dir, relpath_to_analysis, jar_file
        )

        # TODO: Extract something common from Executor._create_command to make the command line
        argv = image_specific_argv + [f"@{argfile_snapshot.files[0]}"]

        merged_input_digest = self.context._scheduler.merge_directories(
            [self._zinc.zinc.directory_digest]
            + [s.directory_digest for s in snapshots]
            + directory_digests
            + native_image_snapshots
            + [self.post_compile_extra_resources_digest(ctx), argfile_snapshot.directory_digest]
        )

        # NB: We always capture the output jar, but if classpath jars are not used, we additionally
        # capture loose classes from the workspace. This is because we need to both:
        #   1) allow loose classes as an input to dependent compiles
        #   2) allow jars to be materialized at the end of the run.
        output_directories = () if self.get_options().use_classpath_jars else (classes_dir,)

        req = Process(
            argv=tuple(argv),
            input_files=merged_input_digest,
            output_files=(jar_file, relpath_to_analysis),
            output_directories=output_directories,
            description=f"zinc compile for {ctx.target.address.spec}",
            unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule=merged_local_only_scratch_inputs,
            jdk_home=self._zinc.underlying_dist.home,
            is_nailgunnable=True,
        )
        res = self.context.execute_process_synchronously_or_raise(
            req, self.name(), [WorkUnitLabel.COMPILER]
        )

        # TODO: Materialize as a batch in do_compile or somewhere
        self.context._scheduler.materialize_directory(
            DirectoryToMaterialize(res.output_directory_digest)
        )

        # TODO: This should probably return a ClasspathEntry rather than a Digest
        return res.output_directory_digest

    def _compute_local_only_inputs(self, classes_dir, relpath_to_analysis, jar_file):
        """Compute for the scratch inputs for Process.

        If analysis file exists, then incremental compile is enabled. Otherwise, the compile is not
        incremental, an empty digest will be returned.

        :param classes_dir: relative path to classes dir from buildroot
        :param relpath_to_analysis: relative path to zinc analysis file from buildroot
        :param jar_file: relative path to z.jar from buildroot
        :return: digest of merged analysis file and loose class files.
        """
        if not os.path.exists(relpath_to_analysis):
            return EMPTY_DIRECTORY_DIGEST

        def _get_analysis_snapshot():
            (_analysis_snapshot,) = self.context._scheduler.capture_snapshots(
                [PathGlobsAndRoot(PathGlobs([relpath_to_analysis]), get_buildroot())]
            )
            return _analysis_snapshot

        def _get_classes_dir_snapshot():
            if self.get_options().use_classpath_jars and os.path.exists(jar_file):
                with zipfile.ZipFile(jar_file, "r") as zip_ref:
                    zip_ref.extractall(classes_dir)

            (_classes_dir_snapshot,) = self.context._scheduler.capture_snapshots(
                [PathGlobsAndRoot(PathGlobs([classes_dir + "/**"]), get_buildroot())]
            )
            return _classes_dir_snapshot

        analysis_snapshot = _get_analysis_snapshot()
        classes_dir_snapshot = _get_classes_dir_snapshot()
        return self.context._scheduler.merge_directories(
            [analysis_snapshot.directory_digest, classes_dir_snapshot.directory_digest]
        )

    def get_zinc_compiler_classpath(self):
        """Get the classpath for the zinc compiler JVM tool.

        This will just be the zinc compiler tool classpath normally, but tasks which invoke zinc
        along with other JVM tools with nailgun (such as RscCompile) require zinc to be invoked with
        this method to ensure a single classpath is used for all the tools they need to invoke so
        that the nailgun instance (which is keyed by classpath and JVM options) isn't invalidated.
        """
        return [self._zinc.zinc.path]

    def _verify_zinc_classpath(self, classpath, allow_dist=True):
        def is_outside(path, putative_parent):
            return os.path.relpath(path, putative_parent).startswith(os.pardir)

        dist = self._zinc.dist
        for path in classpath:
            if not os.path.isabs(path):
                raise TaskError(
                    "Classpath entries provided to zinc should be absolute. "
                    "{} is not.".format(path)
                )

            if is_outside(path, self.get_options().pants_workdir) and (
                not allow_dist or is_outside(path, dist.home)
            ):
                raise TaskError(
                    "Classpath entries provided to zinc should be in working directory or "
                    "part of the JDK. {} is not.".format(path)
                )
            if path != os.path.normpath(path):
                raise TaskError(
                    "Classpath entries provided to zinc should be normalized "
                    '(i.e. without ".." and "."). {} is not.'.format(path)
                )

    def log_zinc_file(self, analysis_file):
        self.context.log.debug(
            "Calling zinc on: {} ({})".format(
                analysis_file,
                hash_file(analysis_file).upper()
                if os.path.exists(analysis_file)
                else "nonexistent",
            )
        )

    @classmethod
    def _javac_plugin_args(cls, javac_plugin_map):
        ret = []
        for plugin, args in javac_plugin_map.items():
            for arg in args:
                if " " in arg:
                    # Note: Args are separated by spaces, and there is no way to escape embedded spaces, as
                    # javac's Main does a simple split on these strings.
                    raise TaskError(
                        "javac plugin args must not contain spaces "
                        "(arg {} for plugin {})".format(arg, plugin)
                    )
            ret.append(f"-C-Xplugin:{plugin} {' '.join(args)}")
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
            ret.append(f"-S-Xplugin:{':'.join(cp_entries)}")
            for arg in scalac_plugin_map[name]:
                ret.append(f"-S-P:{name}:{arg}")
        return ret

    def _find_scalac_plugins(self, scalac_plugins, classpath):
        """Returns a map from plugin name to list of plugin classpath entries.

        The first entry in each list is the classpath entry containing the plugin metadata.
        The rest are the internal transitive deps of the plugin.

        This allows us to have in-repo plugins with dependencies (unlike javac, scalac doesn't load
        plugins or their deps from the regular classpath, so we have to provide these entries
        separately, in the -Xplugin: flag).

        Note that we don't currently support external plugins with dependencies, as we can't know which
        external classpath elements are required, and we'd have to put the entire external classpath
        on each -Xplugin: flag, which seems excessive.
        Instead, external plugins should be published as "fat jars" (which appears to be the norm,
        since SBT doesn't support plugins with dependencies anyway).
        """
        # Allow multiple flags and also comma-separated values in a single flag.
        plugin_names = {p for val in scalac_plugins for p in val.split(",")}
        if not plugin_names:
            return {}

        active_plugins = {}
        buildroot = get_buildroot()

        cp_product = self.context.products.get_data("runtime_classpath")
        for classpath_element in classpath:
            name = self._maybe_get_plugin_name(classpath_element)
            if name in plugin_names:
                plugin_target_closure = self._plugin_targets("scalac").get(name, [])
                # It's important to use relative paths, as the compiler flags get embedded in the zinc
                # analysis file, and we port those between systems via the artifact cache.
                rel_classpath_elements = [
                    os.path.relpath(cpe, buildroot)
                    for cpe in ClasspathUtil.internal_classpath(
                        plugin_target_closure, cp_product, self._confs
                    )
                ]
                # If the plugin is external then rel_classpath_elements will be empty, so we take
                # just the external jar itself.
                rel_classpath_elements = rel_classpath_elements or [classpath_element]
                # Some classpath elements may be repeated, so we allow for that here.
                if active_plugins.get(name, rel_classpath_elements) != rel_classpath_elements:
                    raise TaskError(
                        "Plugin {} defined in {} and in {}".format(
                            name, active_plugins[name], classpath_element
                        )
                    )
                active_plugins[name] = rel_classpath_elements
                if len(active_plugins) == len(plugin_names):
                    # We've found all the plugins, so return now to spare us from processing
                    # of the rest of the classpath for no reason.
                    return active_plugins

        # If we get here we must have unresolved plugins.
        unresolved_plugins = plugin_names - set(active_plugins.keys())
        raise TaskError(f"Could not find requested plugins: {list(unresolved_plugins)}")

    @classmethod
    @memoized_method
    def _maybe_get_plugin_name(cls, classpath_element):
        """If classpath_element is a scalac plugin, returns its name.

        Returns None otherwise.
        """

        def process_info_file(cp_elem, info_file):
            plugin_info = ElementTree.parse(info_file).getroot()
            if plugin_info.tag != "plugin":
                raise TaskError(
                    "File {} in {} is not a valid scalac plugin descriptor".format(
                        _SCALAC_PLUGIN_INFO_FILE, cp_elem
                    )
                )
            return plugin_info.find("name").text

        if os.path.isdir(classpath_element):
            try:
                with open(
                    os.path.join(classpath_element, _SCALAC_PLUGIN_INFO_FILE), "r"
                ) as plugin_info_file:
                    return process_info_file(classpath_element, plugin_info_file)
            except IOError as e:
                if e.errno != errno.ENOENT:
                    raise
        else:
            with open_zip(classpath_element, "r") as jarfile:
                try:
                    with closing(jarfile.open(_SCALAC_PLUGIN_INFO_FILE, "r")) as plugin_info_file:
                        return process_info_file(classpath_element, plugin_info_file)
                except KeyError:
                    pass
        return None


class ZincCompile(BaseZincCompile):
    """Compile Scala and Java code to classfiles using Zinc."""

    compiler_name = "zinc"

    @classmethod
    def product_types(cls):
        return super().product_types(cls) + [
            "runtime_classpath",
            "zinc_analysis",
            "zinc_args",
            "jvm_modulizable_targets",
        ]

    @staticmethod
    def select(target):
        # Require that targets are marked for JVM compilation, to differentiate from
        # targets owned by the scalajs contrib module.
        if not isinstance(target, JvmTarget):
            return False
        return target.has_sources(".java") or target.has_sources(".scala")

    def select_source(self, source_file_path):
        return source_file_path.endswith(".java") or source_file_path.endswith(".scala")

    def calculate_jvm_modulizable_targets(self):
        if not self.context.products.is_required_data("jvm_modulizable_targets"):
            return set()

        def is_jvm_or_resource_target(t):
            return isinstance(t, (JvmTarget, JvmApp, JarLibrary, Resources))

        jvm_and_resources_target_roots = set(
            filter(is_jvm_or_resource_target, self.context.target_roots)
        )
        jvm_and_resources_target_roots_minus_synthetic_addresses = set(
            t.address for t in filter(lambda x: not x.is_synthetic, jvm_and_resources_target_roots)
        )
        all_targets = set(self.context.targets())
        modulizable_targets = set(
            t
            for t in self.context.build_graph.transitive_dependees_of_addresses(
                jvm_and_resources_target_roots_minus_synthetic_addresses,
                # A predicate is required here because it's possible other injected targets
                # could show up as dependees. (##9179)
                predicate=lambda x: x in all_targets,
            )
            if is_jvm_or_resource_target(t)
        )
        synthetic_modulizable_targets = set(filter(lambda x: x.is_synthetic, modulizable_targets))
        if len(synthetic_modulizable_targets) > 0:
            # TODO(yic): improve the error message to show the dependency chain that caused
            # a synthetic target depending on a non-synthetic one.
            raise TaskError(
                f"Modulizable targets must not contain any synthetic target, but in this case the "
                f"following synthetic targets depend on other non-synthetic modules:\n"
                f"{synthetic_modulizable_targets}\n"
                f"One approach that may help is to reduce the scope of the import to further avoid synthetic targets."
            )

        self.context.products.get_data("jvm_modulizable_targets", set).update(modulizable_targets)
        return modulizable_targets
