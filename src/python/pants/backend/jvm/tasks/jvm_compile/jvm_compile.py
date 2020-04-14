# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import os
from enum import Enum
from multiprocessing import cpu_count
from typing import Optional, Set

from pants.backend.jvm.subsystems.dependency_context import DependencyContext
from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.zinc import Zinc
from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.javac_plugin import JavacPlugin
from pants.backend.jvm.targets.scalac_plugin import ScalacPlugin
from pants.backend.jvm.tasks.classpath_entry import ClasspathEntry
from pants.backend.jvm.tasks.jvm_compile.class_not_found_error_patterns import (
    CLASS_NOT_FOUND_ERROR_PATTERNS,
)
from pants.backend.jvm.tasks.jvm_compile.compile_context import CompileContext
from pants.backend.jvm.tasks.jvm_compile.execution_graph import (
    ExecutionFailure,
    ExecutionGraph,
    Job,
)
from pants.backend.jvm.tasks.jvm_compile.missing_dependency_finder import (
    CompileErrorExtractor,
    MissingDependencyFinder,
)
from pants.backend.jvm.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.backend.jvm.tasks.nailgun_task import NailgunTaskBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.worker_pool import WorkerPool
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.target import Target
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, PathGlobs, PathGlobsAndRoot
from pants.java.distribution.distribution import DistributionLocator
from pants.option.compiler_option_sets_mixin import CompilerOptionSetsMixin
from pants.option.ranked_value import RankedValue
from pants.reporting.reporting_utils import items_to_report_element
from pants.util.contextutil import Timer, temporary_dir
from pants.util.dirutil import (
    fast_relpath,
    read_file,
    safe_delete,
    safe_file_dump,
    safe_mkdir,
    safe_rmtree,
)
from pants.util.enums import match
from pants.util.fileutil import create_size_estimators
from pants.util.memo import memoized_method, memoized_property

# Well known metadata file to register javac plugins.
_JAVAC_PLUGIN_INFO_FILE = "META-INF/services/com.sun.source.util.Plugin"

# Well known metadata file to register annotation processors with a java 1.6+ compiler.
_PROCESSOR_INFO_FILE = "META-INF/services/javax.annotation.processing.Processor"


class JvmCompile(CompilerOptionSetsMixin, NailgunTaskBase):
    """A common framework for JVM compilation.

    To subclass for a specific JVM language, implement the static values and methods mentioned below
    under "Subclasses must implement".
    """

    size_estimators = create_size_estimators()

    class Compiler(Enum):
        ZINC = "zinc"
        RSC = "rsc"
        JAVAC = "javac"

    @classmethod
    def size_estimator_by_name(cls, estimation_strategy_name):
        return cls.size_estimators[estimation_strategy_name]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--args",
            advanced=True,
            type=list,
            default=list(cls.get_args_default(register.bootstrap)),
            fingerprint=True,
            help="Pass these extra args to the compiler.",
        )

        register(
            "--clear-invalid-analysis",
            advanced=True,
            type=bool,
            help="When set, any invalid/incompatible analysis files will be deleted "
            "automatically.  When unset, an error is raised instead.",
        )

        # TODO(#7682): convert these into option sets!
        register(
            "--warnings",
            default=True,
            type=bool,
            fingerprint=True,
            help="Compile with all configured warnings enabled.",
        )

        register(
            "--warning-args",
            advanced=True,
            type=list,
            fingerprint=True,
            default=list(cls.get_warning_args_default()),
            help="Extra compiler args to use when warnings are enabled.",
        )

        register(
            "--no-warning-args",
            advanced=True,
            type=list,
            fingerprint=True,
            default=list(cls.get_no_warning_args_default()),
            help="Extra compiler args to use when warnings are disabled.",
        )

        register(
            "--compiler-option-sets-enabled-scalac-plugins",
            advanced=True,
            type=dict,
            fingerprint=True,
            help="A mapping of (compiler option set name) -> (list of scalac plugin names to "
            "be enabled when this option set is enabled).",
        )

        register(
            "--debug-symbols",
            type=bool,
            fingerprint=True,
            help="Compile with debug symbol enabled.",
        )

        register(
            "--debug-symbol-args",
            advanced=True,
            type=list,
            fingerprint=True,
            default=["-C-g:lines,source,vars"],
            help="Extra args to enable debug symbol.",
        )

        register(
            "--delete-scratch",
            advanced=True,
            default=True,
            type=bool,
            help="Leave intermediate scratch files around, for debugging build problems.",
        )

        register(
            "--worker-count",
            advanced=True,
            type=int,
            default=cpu_count(),
            help="The number of concurrent workers to use when "
            "compiling with {task}. Defaults to the "
            "current machine's CPU count.".format(task=cls._name),
        )

        register(
            "--size-estimator",
            advanced=True,
            choices=list(cls.size_estimators.keys()),
            default="filesize",
            help="The method of target size estimation. The size estimator estimates the size "
            "of targets in order to build the largest targets first (subject to dependency "
            "constraints). Choose 'random' to choose random sizes for each target, which "
            "may be useful for distributed builds.",
        )

        register(
            "--capture-classpath",
            advanced=True,
            type=bool,
            default=True,
            fingerprint=True,
            help="Capture classpath to per-target newline-delimited text files. These files will "
            "be packaged into any jar artifacts that are created from the jvm targets.",
        )

        register(
            "--suggest-missing-deps",
            type=bool,
            help="Suggest missing dependencies on a best-effort basis from target's transitive"
            "deps for compilation failures that are due to class not found.",
        )

        register(
            "--buildozer",
            help="Path to buildozer for suggest-missing-deps command lines. "
            "If absent, no command line will be suggested to fix missing deps.",
        )

        register(
            "--missing-deps-not-found-msg",
            advanced=True,
            type=str,
            help="The message to print when pants can't find any suggestions for targets "
            "containing the classes not found during compilation. This should "
            "likely include a link to documentation about dependency management.",
            default="Please see https://www.pantsbuild.org/3rdparty_jvm.html#strict-dependencies "
            "for more information.",
        )

        register(
            "--class-not-found-error-patterns",
            advanced=True,
            type=list,
            default=CLASS_NOT_FOUND_ERROR_PATTERNS,
            help="List of regular expression patterns that extract class not found "
            "compile errors.",
        )

        register(
            "--use-classpath-jars",
            advanced=True,
            type=bool,
            fingerprint=True,
            help="Use jar files on the compile_classpath. Note: Using this option degrades "
            "incremental compile between targets.",
        )

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("JvmCompile", 3)]

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)

        round_manager.require_data("compile_classpath")

        # Require codegen we care about
        # TODO(John Sirois): roll this up in Task - if the list of labels we care about for a target
        # predicate to filter the full build graph is exposed, the requirement can be made automatic
        # and in turn codegen tasks could denote the labels they produce automating wiring of the
        # produce side
        round_manager.optional_data("java")
        round_manager.optional_data("scala")

        # Allow the deferred_sources_mapping to take place first
        round_manager.optional_data("deferred_sources")

    # Subclasses must implement.
    # --------------------------
    _name: Optional[str] = None
    # The name used in JvmPlatform to refer to this compiler task.
    compiler_name: Optional[str] = None

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (
            DependencyContext,
            Java,
            JvmPlatform,
            ScalaPlatform,
            Zinc.Factory,
        )

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
    def cache_target_dirs(self):
        return True

    @memoized_property
    def _zinc(self):
        return Zinc.Factory.global_instance().create(self.context.products, self.execution_strategy)

    def _zinc_tool_classpath(self, toolname):
        return self._zinc.tool_classpath_from_products(
            self.context.products, toolname, scope=self.options_scope
        )

    def _zinc_tool_jar(self, toolname):
        return self._zinc.tool_jar_from_products(
            self.context.products, toolname, scope=self.options_scope
        )

    def select(self, target):
        raise NotImplementedError()

    def select_source(self, source_file_path):
        raise NotImplementedError()

    def product_types(cls):
        return super(JvmCompile, cls).product_types()

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
        """Invoke the compiler.

        Subclasses must implement. Must raise TaskError on compile failure.

        :param CompileContext ctx: A CompileContext for the target to compile.
        :param list args: Arguments to the compiler (such as javac or zinc).
        :param list dependency_classpath: List of classpath entries of type ClasspathEntry for
          dependencies.
        :param upstream_analysis: A map from classpath entry to analysis file for dependencies.
        :param JvmPlatformSettings settings: platform settings determining the -source, -target, etc for
          javac to use.
        :param list compiler_option_sets: The compiler_option_sets flags for the target.
        :param zinc_file_manager: whether to use zinc provided file manager.
        :param javac_plugin_map: Map of names of javac plugins to use to their arguments.
        :param scalac_plugin_map: Map of names of scalac plugins to use to their arguments.
        """
        raise NotImplementedError()

    # Subclasses may override.
    # ------------------------

    def extra_compile_time_classpath_elements(self):
        """Extra classpath elements common to all compiler invocations.

        These should be of type ClasspathEntry, but strings are also supported for backwards
        compatibility.

        E.g., jars for compiler plugins.

        These are added at the end of the classpath, after any dependencies, so that if they
        overlap with any explicit dependencies, the compiler sees those first.  This makes
        missing dependency accounting much simpler.
        """
        return []

    def scalac_plugin_classpath_elements(self):
        """Classpath entries containing scalac plugins."""
        return []

    def post_compile_extra_resources(self, compile_context):
        """Produces a dictionary of any extra, out-of-band resources for a target.

        E.g., targets that produce scala compiler plugins or annotation processor files
        produce an info file. The resources will be added to the runtime_classpath.
        :return: A dict from classpath-relative filename to file content.
        """
        result = {}
        target = compile_context.target

        if isinstance(target, JavacPlugin):
            result[_JAVAC_PLUGIN_INFO_FILE] = target.classname
        elif isinstance(target, AnnotationProcessor) and target.processors:
            result[_PROCESSOR_INFO_FILE] = "{}\n".format(
                "\n".join(p.strip() for p in target.processors)
            )

        return result

    def post_compile_extra_resources_digest(
        self, compile_context, prepend_post_merge_relative_path=True
    ):
        """Compute a Digest for the post_compile_extra_resources for the given context."""
        # TODO: Switch to using #7739 once it is available.
        extra_resources = self.post_compile_extra_resources(compile_context)
        if not extra_resources:
            return EMPTY_DIRECTORY_DIGEST

        def _snapshot_resources(resources, prefix="."):
            with temporary_dir() as root_dir:
                for filename, filecontent in resources.items():
                    safe_file_dump(
                        os.path.join(os.path.join(root_dir, prefix), filename), filecontent
                    )

                extra_resources_relative_to_rootdir = {
                    os.path.join(prefix, k): v for k, v in resources.items()
                }
                (snapshot,) = self.context._scheduler.capture_snapshots(
                    [PathGlobsAndRoot(PathGlobs(extra_resources_relative_to_rootdir), root_dir)]
                )

            return snapshot.directory_digest

        if prepend_post_merge_relative_path:
            rel_post_compile_merge_dir = fast_relpath(
                compile_context.post_compile_merge_dir, get_buildroot()
            )
            return _snapshot_resources(extra_resources, prefix=rel_post_compile_merge_dir)
        else:
            return _snapshot_resources(extra_resources)

    def write_argsfile(self, ctx, args):
        """Write the argsfile for this context."""
        with open(ctx.args_file, "w") as fp:
            for arg in args:
                fp.write(arg)
                fp.write("\n")

    def create_empty_extra_products(self):
        """Create any products the subclass task supports in addition to the runtime_classpath.

        The runtime_classpath is constructed by default.
        """

    def create_extra_products_for_targets(self, targets):
        """Allows subclasses to provide a method which creates extra products directly."""

    def register_extra_products_from_contexts(self, targets, compile_contexts):
        """Allows subclasses to register additional products for targets.

        It is called for valid targets at start, then for each completed invalid target, separately,
        during compilation.
        """

    def select_runtime_context(self, ccs):
        """Select the context that contains the paths for runtime classpath artifacts.

        Subclasses may have more than one type of context.
        """
        return ccs

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._targets_to_compile_settings = None

        # TODO: self._jvm_options doesn't seem to record changes from `--<scope>-jvm-options` on the
        # command line (but this might work in pants.toml?)!
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
        self._confs = Zinc.DEFAULT_CONFS

        # Determines which sources are relevant to this target.
        self._sources_predicate = self.select_source

        self._delete_scratch = self.get_options().delete_scratch
        self._clear_invalid_analysis = self.get_options().clear_invalid_analysis

        try:
            worker_count = self.get_options().worker_count
        except AttributeError:
            # tasks that don't support concurrent execution have no worker_count registered
            worker_count = 1
        self._worker_count = worker_count

        self._size_estimator = self.size_estimator_by_name(self.get_options().size_estimator)

    @memoized_property
    def _missing_deps_finder(self):
        dep_analyzer = JvmDependencyAnalyzer(
            get_buildroot(),
            self._get_jvm_distribution(),
            self.context.products.get_data("runtime_classpath"),
        )
        return MissingDependencyFinder(
            dep_analyzer, CompileErrorExtractor(self.get_options().class_not_found_error_patterns)
        )

    def create_compile_context(self, target, target_workdir):
        return CompileContext(
            target=target,
            analysis_file=os.path.join(target_workdir, "z.analysis"),
            classes_dir=ClasspathEntry(os.path.join(target_workdir, "classes")),
            jar_file=ClasspathEntry(os.path.join(target_workdir, "z.jar")),
            log_dir=os.path.join(target_workdir, "logs"),
            args_file=os.path.join(target_workdir, "zinc_args"),
            post_compile_merge_dir=os.path.join(target_workdir, "post_compile_merge_dir"),
            sources=self._compute_sources_for_target(target),
            diagnostics_out=None,
        )

    def execute(self):
        requested_compiler = JvmPlatform.global_instance().get_options().compiler
        if requested_compiler != self.compiler_name:
            return

        if requested_compiler == self.Compiler.ZINC and self.compiler_name == self.Compiler.RSC:
            # Issue a deprecation warning (above) and rewrite zinc to rsc, as zinc is being deprecated.
            JvmPlatform.global_instance().get_options().compiler = RankedValue(
                0, self.compiler_name
            )
        elif requested_compiler != self.compiler_name:
            # If the requested compiler is not the one supported by this task, log and abort
            self.context.log.debug(
                f"Requested an unsupported compiler [{requested_compiler}], aborting"
            )
            return

        # In case we have no relevant targets and return early, create the requested product maps.
        self.create_empty_extra_products()

        # Clone the compile_classpath to the runtime_classpath.
        classpath_product = self.create_classpath_product()

        fingerprint_strategy = DependencyContext.global_instance().create_fingerprint_strategy(
            classpath_product
        )

        relevant_targets = list(self.context.targets(predicate=self.select))

        modulizable_targets = self.calculate_jvm_modulizable_targets()
        if modulizable_targets:
            # If we are only exporting jars then we can omit some targets from the runtime_classpath.
            relevant_targets = list(
                filter(lambda x: self.select(x), set(relevant_targets) - modulizable_targets)
            )

        if relevant_targets:
            # Note, JVM targets are validated (`vts.update()`) as they succeed.  As a result,
            # we begin writing artifacts out to the cache immediately instead of waiting for
            # all targets to finish.
            with self.invalidated(
                relevant_targets,
                invalidate_dependents=True,
                fingerprint_strategy=fingerprint_strategy,
                topological_order=True,
            ) as invalidation_check:
                compile_contexts = {
                    vt.target: self.create_compile_context(vt.target, vt.results_dir)
                    for vt in invalidation_check.all_vts
                }

                self.do_compile(
                    invalidation_check, compile_contexts, classpath_product,
                )

                if not self.get_options().use_classpath_jars:
                    # Once compilation has completed, replace the classpath entry for each target with
                    # its jar'd representation.
                    for ccs in compile_contexts.values():
                        cc = self.select_runtime_context(ccs)
                        for conf in self._confs:
                            classpath_product.remove_for_target(cc.target, [(conf, cc.classes_dir)])
                            classpath_product.add_for_target(cc.target, [(conf, cc.jar_file)])

        if modulizable_targets:
            compilable_modulizable_targets = set(
                filter(lambda x: self.select(x), modulizable_targets)
            )
            self.create_extra_products_for_targets(compilable_modulizable_targets)

    def calculate_jvm_modulizable_targets(self) -> Set[Target]:
        """Used to calculate the targets that should be exported to IDEs as modules and therefore
        should not be compiled."""
        return set()

    def _classpath_for_context(self, context):
        if self.get_options().use_classpath_jars:
            return context.jar_file
        return context.classes_dir

    def create_classpath_product(self):
        compile_classpath = self.context.products.get_data("compile_classpath")
        classpath_product = self.context.products.get_data("runtime_classpath")
        if not classpath_product:
            classpath_product = self.context.products.get_data(
                "runtime_classpath", compile_classpath.copy
            )
        else:
            classpath_product.update(compile_classpath)

        return classpath_product

    def do_compile(self, invalidation_check, compile_contexts, classpath_product):
        """Executes compilations for the invalid targets contained in a single chunk."""

        invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]
        valid_targets = [vt.target for vt in invalidation_check.all_vts if vt.valid]

        if self.execution_strategy == self.ExecutionStrategy.hermetic:
            self._set_directory_digests_for_valid_target_classpath_directories(
                valid_targets, compile_contexts
            )

        for valid_target in valid_targets:
            cc = self.select_runtime_context(compile_contexts[valid_target])

            classpath_product.add_for_target(
                valid_target, [(conf, self._classpath_for_context(cc)) for conf in self._confs],
            )
        self.register_extra_products_from_contexts(valid_targets, compile_contexts)

        if invalid_targets:
            # This ensures the workunit for the worker pool is set before attempting to compile.
            with self.context.new_workunit(f"isolation-{self.name()}-pool-bootstrap") as workunit:
                # This uses workunit.parent as the WorkerPool's parent so that child workunits
                # of different pools will show up in order in the html output. This way the current running
                # workunit is on the bottom of the page rather than possibly in the middle.
                worker_pool = WorkerPool(
                    workunit.parent, self.context.run_tracker, self._worker_count, workunit.name
                )

            # Prepare the output directory for each invalid target, and confirm that analysis is valid.
            for target in invalid_targets:
                cc = self.select_runtime_context(compile_contexts[target])
                safe_mkdir(cc.classes_dir.path)

            # Now create compile jobs for each invalid target one by one, using the classpath
            # generated by upstream JVM tasks and our own prepare_compile().
            jobs = self._create_compile_jobs(
                compile_contexts, invalid_targets, invalidation_check.invalid_vts, classpath_product
            )

            exec_graph = ExecutionGraph(jobs, self.get_options().print_exception_stacktrace)
            try:
                exec_graph.execute(worker_pool, self.context.log)
            except ExecutionFailure as e:
                raise TaskError(f"Compilation failure: {e!r}")

    def _record_compile_classpath(self, classpath, target, outdir):
        relative_classpaths = [
            fast_relpath(path, self.get_options().pants_workdir) for path in classpath
        ]
        text = "\n".join(relative_classpaths)
        path = os.path.join(outdir, "compile_classpath", f"{target.id}.txt")
        safe_mkdir(os.path.dirname(path), clean=False)
        with open(path, "w") as f:
            f.write(text)

    def _set_directory_digests_for_valid_target_classpath_directories(
        self, valid_targets, compile_contexts
    ):
        def _get_relative_classpath_for_target(target):
            cc = self.select_runtime_context(compile_contexts[target])
            if self.get_options().use_classpath_jars:
                return fast_relpath(cc.jar_file.path, get_buildroot())
            else:
                return fast_relpath(cc.classes_dir.path, get_buildroot()) + "/**"

        snapshots = self.context._scheduler.capture_snapshots(
            tuple(
                PathGlobsAndRoot(
                    PathGlobs([_get_relative_classpath_for_target(target)]), get_buildroot()
                )
                for target in valid_targets
            )
        )
        for target, snapshot in list(zip(valid_targets, snapshots)):
            cc = self.select_runtime_context(compile_contexts[target])
            self._set_directory_digest_for_compile_context(cc, snapshot.directory_digest)

    def _set_directory_digest_for_compile_context(self, ctx, directory_digest):
        if self.get_options().use_classpath_jars:
            ctx.jar_file = ClasspathEntry(ctx.jar_file.path, directory_digest)
        else:
            ctx.classes_dir = ClasspathEntry(ctx.classes_dir.path, directory_digest)

    def _compile_vts(
        self,
        vts,
        ctx,
        upstream_analysis,
        dependency_classpath,
        progress_message,
        settings,
        compiler_option_sets,
        zinc_file_manager,
        counter,
    ):
        """Compiles sources for the given vts into the given output dir.

        :param vts: VersionedTargetSet with one entry for the target.
        :param ctx: - A CompileContext instance for the target.
        :param dependency_classpath: A list of classpath entries of type ClasspathEntry for dependencies

        May be invoked concurrently on independent target sets.

        Postcondition: The individual targets in vts are up-to-date, as if each were
                       compiled individually.
        """
        if not ctx.sources:
            self.context.log.warn(
                "Skipping {} compile for targets with no sources:\n  {}".format(
                    self.name(), vts.targets
                )
            )
        else:
            counter_val = str(counter()).rjust(counter.format_length(), " ")
            counter_str = f"[{counter_val}/{counter.size}] "
            # Do some reporting.
            self.context.log.info(
                counter_str,
                "Compiling ",
                items_to_report_element(ctx.sources, f"{self.name()} source"),
                " in ",
                items_to_report_element([t.address.reference() for t in vts.targets], "target"),
                " (",
                progress_message,
                ").",
            )
            with self.context.new_workunit(
                "compile", labels=[WorkUnitLabel.COMPILER]
            ) as compile_workunit:
                try:
                    directory_digest = self.compile(
                        ctx,
                        self._args,
                        dependency_classpath,
                        upstream_analysis,
                        settings,
                        compiler_option_sets,
                        zinc_file_manager,
                        self._get_plugin_map("javac", Java.global_instance(), ctx.target),
                        self._get_plugin_map("scalac", ScalaPlatform.global_instance(), ctx.target),
                    )
                    self._capture_logs(compile_workunit, ctx.log_dir)
                    return directory_digest
                except TaskError:
                    if self.get_options().suggest_missing_deps:
                        logs = [
                            path
                            for _, name, _, path in self._find_logs(compile_workunit)
                            if name == self.name()
                        ]
                        if logs:
                            self._find_missing_deps(logs, ctx.target)
                    raise

    def _capture_logs(self, workunit, destination):
        safe_mkdir(destination, clean=True)
        for idx, name, output_name, path in self._find_logs(workunit):
            os.link(path, os.path.join(destination, f"{name}-{idx}-{output_name}.log"))

    def _get_plugin_map(self, compiler, options_src, target):
        """Returns a map of plugin to args, for the given compiler.

        Only plugins that must actually be activated will be present as keys in the map.
        Plugins with no arguments will have an empty list as a value.

        Active plugins and their args will be gathered from (in order of precedence):
        - The <compiler>_plugins and <compiler>_plugin_args fields of the target, if it has them.
        - The <compiler>_plugins and <compiler>_plugin_args options of this task, if it has them.
        - The <compiler>_plugins and <compiler>_plugin_args fields of this task, if it has them.

        Note that in-repo plugins will not be returned, even if requested, when building
        themselves.  Use published versions of those plugins for that.

        See:
        - examples/src/java/org/pantsbuild/example/javac/plugin/README.md.
        - examples/src/scala/org/pantsbuild/example/scalac/plugin/README.md

        :param compiler: one of 'javac', 'scalac'.
        :param options_src: A JvmToolMixin instance providing plugin options.
        :param target: The target whose plugins we compute.
        """
        # Note that we get() options and getattr() target fields and task methods,
        # so we're robust when those don't exist (or are None).
        plugins_key = f"{compiler}_plugins"

        dep_context = DependencyContext.global_instance()
        compiler_option_sets = dep_context.defaulted_property(target, "compiler_option_sets")

        requested_plugins = (
            tuple(getattr(self, plugins_key, []) or [])
            + tuple(options_src.get_options().get(plugins_key, []) or [])
            + tuple((getattr(target, plugins_key, []) or []))
            + tuple(
                plugin_name
                for option_set_name in compiler_option_sets
                for plugin_name in self.get_options().compiler_option_sets_enabled_scalac_plugins.get(
                    option_set_name, []
                )
            )
        )
        # Allow multiple flags and also comma-separated values in a single flag.
        requested_plugins = {p for val in requested_plugins for p in val.split(",")}

        plugin_args_key = f"{compiler}_plugin_args"
        available_plugin_args = {}
        available_plugin_args.update(getattr(self, plugin_args_key, {}) or {})
        available_plugin_args.update(options_src.get_options().get(plugin_args_key, {}) or {})
        available_plugin_args.update(getattr(target, plugin_args_key, {}) or {})

        # From all available args, pluck just the ones for the selected plugins.
        plugin_map = {}
        for plugin in requested_plugins:
            # Don't attempt to use a plugin while building that plugin.
            # This avoids a bootstrapping problem.  Note that you can still
            # use published plugins on themselves, just not in-repo plugins.
            if target not in self._plugin_targets(compiler).get(plugin, {}):
                plugin_map[plugin] = available_plugin_args.get(plugin, [])
        return plugin_map

    def _find_logs(self, compile_workunit):
        """Finds all logs under the given workunit."""
        for idx, workunit in enumerate(compile_workunit.children):
            for output_name, outpath in workunit.output_paths().items():
                if output_name in ("stdout", "stderr"):
                    yield idx, workunit.name, output_name, outpath

    def _find_missing_deps(self, compile_logs, target):
        with self.context.new_workunit("missing-deps-suggest", labels=[WorkUnitLabel.COMPILER]):
            compile_failure_log = "\n".join(read_file(log) for log in compile_logs)

            missing_dep_suggestions, no_suggestions = self._missing_deps_finder.find(
                compile_failure_log, target
            )

            if missing_dep_suggestions:
                self.context.log.info(
                    "Found the following deps from target's transitive "
                    "dependencies that provide the missing classes:"
                )
                suggested_deps = set()
                for classname, candidates in missing_dep_suggestions.items():
                    suggested_deps.add(list(candidates)[0])
                    self.context.log.info(f"  {classname}: {', '.join(candidates)}")

                # We format the suggested deps with single quotes and commas so that
                # they can be easily cut/pasted into a BUILD file.
                formatted_suggested_deps = [f"'{dep}'," for dep in suggested_deps]
                suggestion_msg = (
                    "\nIf the above information is correct, "
                    "please add the following to the dependencies of ({}):\n  {}\n".format(
                        target.address.spec, "\n  ".join(sorted(list(formatted_suggested_deps)))
                    )
                )

                path_to_buildozer = self.get_options().buildozer
                if path_to_buildozer:
                    suggestion_msg += (
                        "\nYou can do this by running:\n"
                        "  {buildozer} 'add dependencies {deps}' {target}".format(
                            buildozer=path_to_buildozer,
                            deps=" ".join(sorted(suggested_deps)),
                            target=target.address.spec,
                        )
                    )

                self.context.log.info(suggestion_msg)

            if no_suggestions:
                self.context.log.warn(
                    "Unable to find any deps from target's transitive "
                    "dependencies that provide the following missing classes:"
                )
                no_suggestion_msg = "\n   ".join(sorted(list(no_suggestions)))
                self.context.log.warn(f"  {no_suggestion_msg}")
                self.context.log.warn(self.get_options().missing_deps_not_found_msg)

    def _upstream_analysis(self, compile_contexts, classpath_entries):
        """Returns tuples of classes_dir->analysis_file for the closure of the target."""
        # Reorganize the compile_contexts by class directory.
        compile_contexts_by_directory = {}
        for compile_context in compile_contexts.values():
            compile_context = self.select_runtime_context(compile_context)
            compile_contexts_by_directory[compile_context.classes_dir.path] = compile_context
        # If we have a compile context for the target, include it.
        for entry in classpath_entries:
            path = entry.path
            if not path.endswith(".jar"):
                compile_context = compile_contexts_by_directory.get(path)
                if not compile_context:
                    self.context.log.debug(f"Missing upstream analysis for {path}")
                else:
                    yield compile_context.classes_dir.path, compile_context.analysis_file

    def exec_graph_double_check_cache_key_for_target(self, target):
        return f"double_check_cache({target.address.spec})"

    def exec_graph_key_for_target(self, compile_target):
        return f"compile({compile_target.address.spec})"

    def _create_compile_jobs(
        self, compile_contexts, invalid_targets, invalid_vts, classpath_product
    ):
        class Counter:
            def __init__(self, size=0):
                self.size = size
                self.count = 0

            def __call__(self):
                self.count += 1
                return self.count

            def increment_size(self, by=1):
                self.size += by

            def format_length(self):
                return len(str(self.size))

        jobs = []
        counter = Counter()

        invalid_target_set = set(invalid_targets)
        for ivts in invalid_vts:
            # Invalidated targets are a subset of relevant targets: get the context for this one.
            compile_target = ivts.target
            invalid_dependencies = self._collect_invalid_compile_dependencies(
                compile_target, invalid_target_set
            )

            new_jobs, new_count = self.create_compile_jobs(
                compile_target,
                compile_contexts,
                invalid_dependencies,
                ivts,
                counter,
                classpath_product,
            )
            jobs.extend(new_jobs)
            counter.increment_size(by=new_count)

        return jobs

    def create_compile_jobs(
        self,
        compile_target,
        all_compile_contexts,
        invalid_dependencies,
        ivts,
        counter,
        classpath_product,
    ):
        """Return a list of jobs, and a count of those jobs that represent meaningful ("countable")
        work."""

        context_for_target = all_compile_contexts[compile_target]
        compile_context = self.select_runtime_context(context_for_target)

        compile_deps = [self.exec_graph_key_for_target(target) for target in invalid_dependencies]

        # The cache checking job doesn't technically have any dependencies, but we want to delay it
        # until immediately before we would otherwise try compiling, so we indicate that it depends on
        # all compile dependencies.
        double_check_cache_job = Job(
            key=self.exec_graph_double_check_cache_key_for_target(compile_target),
            fn=functools.partial(self._default_double_check_cache_for_vts, ivts),
            dependencies=compile_deps,
            options_scope=self.options_scope,
            target=compile_target,
        )
        # The compile job depends on the cache check job. This decomposition is necessary in order to
        # support more complex situations where compilation runs multiple jobs in parallel, and wants to
        # double check the cache before starting any of them.
        compile_job = Job(
            key=self.exec_graph_key_for_target(compile_target),
            fn=functools.partial(
                self._default_work_for_vts,
                ivts,
                compile_context,
                "runtime_classpath",
                counter,
                all_compile_contexts,
                classpath_product,
            ),
            dependencies=[double_check_cache_job.key] + compile_deps,
            size=self._size_estimator(compile_context.sources),
            # If compilation and analysis work succeeds, validate the vts.
            # Otherwise, fail it.
            on_success=ivts.update,
            on_failure=ivts.force_invalidate,
            options_scope=self.options_scope,
            target=compile_target,
        )
        return ([double_check_cache_job, compile_job], 1)

    def check_cache(self, vts):
        """Manually checks the artifact cache (usually immediately before compilation.)

        Returns true if the cache was hit successfully, indicating that no compilation is necessary.
        """
        if not self.artifact_cache_reads_enabled():
            return False
        cached_vts, _, _ = self.check_artifact_cache([vts])
        if not cached_vts:
            self.context.log.debug(
                "Missed cache during double check for {}".format(vts.target.address.spec)
            )
            return False
        assert cached_vts == [vts], f"Cache returned unexpected target: {cached_vts} vs {[vts]}"
        self.context.log.info(f"Hit cache during double check for {vts.target.address.spec}")
        return True

    def should_compile_incrementally(self, vts, ctx):
        """Check to see if the compile should try to re-use the existing analysis.

        Returns true if we should try to compile the target incrementally.
        """
        if not vts.is_incremental:
            return False
        if not self._clear_invalid_analysis:
            return True
        return os.path.exists(ctx.analysis_file)

    def _record_target_stats(
        self, target, classpath_len, sources_len, compiletime, is_incremental, stats_key
    ):
        # TODO: classpath_len doesn't *really* capture what we're looking for -- the cumulative size of
        # classpath files might be, though. Capturing the digest of the input classpath might give us
        # that, though (as well as the source files?).
        def record(k, v):
            self.context.run_tracker.report_target_info(
                self.options_scope, target, [stats_key, k], v
            )

        self.context.log.debug(
            f"self.options_scope:{self.options_scope}, target:{target}, stats_key:{stats_key}"
        )
        self.context.log.debug(
            "[Timing({})] {}: {} sec; {} sources; {} classpath elements".format(
                stats_key, target.address.spec, compiletime, sources_len, classpath_len
            )
        )
        record("time", compiletime)
        record("classpath_len", classpath_len)
        record("sources_len", sources_len)
        record("incremental", is_incremental)

    def record_extra_target_stats(self, ctx):
        """Report some additional stats for one of the subclasses by overriding this method."""
        return

    def _collect_invalid_compile_dependencies(self, compile_target, invalid_target_set):
        all_strict_deps = DependencyContext.global_instance().dependencies_respecting_strict_deps(
            compile_target
        )
        return list(set(invalid_target_set) & set(all_strict_deps) - set([compile_target]))

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
        if hasattr(target, "java_sources") and target.java_sources:
            sources.extend(resolve_target_sources(target.java_sources))
        return sources

    @memoized_property
    def _extra_compile_time_classpath(self):
        """Compute any extra compile-time-only classpath elements."""

        def extra_compile_classpath_iter():
            for conf in self._confs:
                for jar in self.extra_compile_time_classpath_elements():
                    yield (conf, jar)

        return list(extra_compile_classpath_iter())

    @memoized_method
    def _plugin_targets(self, compiler):
        """Returns a map from plugin name to the targets that build that plugin."""
        if compiler == "javac":
            plugin_cls = JavacPlugin
        elif compiler == "scalac":
            plugin_cls = ScalacPlugin
        else:
            raise TaskError(f"Unknown JVM compiler: {compiler}")
        plugin_tgts = self.context.targets(predicate=lambda t: isinstance(t, plugin_cls))
        return {t.plugin: t.closure() for t in plugin_tgts}

    @staticmethod
    def _local_jvm_distribution(settings=None):
        settings_args = [settings] if settings else []
        try:
            local_distribution = JvmPlatform.preferred_jvm_distribution(settings_args, strict=True)
        except DistributionLocator.Error:
            local_distribution = JvmPlatform.preferred_jvm_distribution(settings_args, strict=False)
        return local_distribution

    class _HermeticDistribution(object):
        def __init__(self, home_path, distribution):
            self._underlying = distribution
            self._home = home_path

        def find_libs(self, names):
            underlying_libs = self._underlying.find_libs(names)
            return [self._rehome(l) for l in underlying_libs]

        def find_libs_path_globs(self, names):
            path_globs = []
            filenames = []
            # We have to move the jars to top level directory because globbing jdk home with symlinks
            # would cause failing to scan the directory. https://github.com/pantsbuild/pants/issues/8460
            for lib_abs in self._underlying.find_libs(names):
                root = os.path.dirname(lib_abs)
                filename = os.path.basename(lib_abs)
                filenames.append(filename)
                path_globs.append(PathGlobsAndRoot(PathGlobs((filename,)), root))
            return (filenames, path_globs)

        @property
        def java(self):
            return os.path.join(self._home, "bin", "java")

        @property
        def home(self):
            return self._home

        @property
        def underlying_home(self):
            return self._underlying.home

        def _unroot_lib_path(self, path):
            return path[len(self._underlying.home) + 1 :]

        def _rehome(self, l):
            return os.path.join(self._home, self._unroot_lib_path(l))

    def _get_jvm_distribution(self):
        # TODO We may want to use different jvm distributions depending on what
        # java version the target expects to be compiled against.
        # See: https://github.com/pantsbuild/pants/issues/6416 for covering using
        #      different jdks in remote builds.
        local_distribution = self._local_jvm_distribution()
        return match(
            self.execution_strategy,
            {
                self.ExecutionStrategy.subprocess: lambda: local_distribution,
                self.ExecutionStrategy.nailgun: lambda: local_distribution,
                self.ExecutionStrategy.hermetic: lambda: self._HermeticDistribution(
                    ".jdk", local_distribution
                ),
            },
        )()

    def _default_double_check_cache_for_vts(self, vts):
        # Double check the cache before beginning compilation
        if self.check_cache(vts):
            vts.update()

    def _default_work_for_vts(
        self,
        vts,
        ctx,
        input_classpath_product_key,
        counter,
        all_compile_contexts,
        output_classpath_product,
    ):
        progress_message = ctx.target.address.spec

        # See whether the cache-doublecheck job hit the cache: if so, noop: otherwise, compile.
        if vts.valid:
            counter()
        else:
            # Compute the compile classpath for this target.
            dependency_cp_entries = self._zinc.compile_classpath_entries(
                input_classpath_product_key,
                ctx.target,
                extra_cp_entries=self._extra_compile_time_classpath,
            )

            upstream_analysis = dict(
                self._upstream_analysis(all_compile_contexts, dependency_cp_entries)
            )

            is_incremental = self.should_compile_incrementally(vts, ctx)
            if not is_incremental:
                # Purge existing analysis file in non-incremental mode.
                safe_delete(ctx.analysis_file)
                # Work around https://github.com/pantsbuild/pants/issues/3670
                safe_rmtree(ctx.classes_dir.path)

            dep_context = DependencyContext.global_instance()
            (tgt,) = vts.targets
            compiler_option_sets = dep_context.defaulted_property(tgt, "compiler_option_sets")
            zinc_file_manager = dep_context.defaulted_property(tgt, "zinc_file_manager")
            with Timer() as timer:
                directory_digest = self._compile_vts(
                    vts,
                    ctx,
                    upstream_analysis,
                    dependency_cp_entries,
                    progress_message,
                    tgt.platform,
                    compiler_option_sets,
                    zinc_file_manager,
                    counter,
                )

            # Store the produced Digest (if any).
            self._set_directory_digest_for_compile_context(ctx, directory_digest)

            self._record_target_stats(
                tgt,
                len(dependency_cp_entries),
                len(ctx.sources),
                timer.elapsed,
                is_incremental,
                "compile",
            )
            self.record_extra_target_stats(ctx)

        # Update the products with the latest classes.
        output_classpath_product.add_for_target(
            ctx.target, [(conf, self._classpath_for_context(ctx)) for conf in self._confs],
        )
        self.register_extra_products_from_contexts([ctx.target], all_compile_contexts)
