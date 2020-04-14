# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import subprocess
from pathlib import Path

from pants.backend.jvm import argfile
from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.engine.fs import DirectoryToMaterialize
from pants.engine.isolated_process import Process
from pants.java.distribution.distribution import DistributionLocator
from pants.util.dirutil import fast_relpath, safe_walk
from pants.util.meta import classproperty

logger = logging.getLogger(__name__)


class JavacCompile(JvmCompile):
    """Compile Java code using Javac."""

    _name = "java"
    compiler_name = "javac"

    @classmethod
    def get_args_default(cls, bootstrap_option_values):
        return ("-encoding", "UTF-8")

    @classmethod
    def get_warning_args_default(cls):
        return ("-deprecation", "-Xlint:all", "-Xlint:-serial", "-Xlint:-path")

    @classmethod
    def get_no_warning_args_default(cls):
        return (
            "-nowarn",
            "-Xlint:none",
        )

    @classproperty
    def get_fatal_warnings_enabled_args_default(cls):
        return ("-Werror",)

    @classproperty
    def get_fatal_warnings_disabled_args_default(cls):
        return ()

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (JvmPlatform,)

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)

    @classmethod
    def product_types(cls):
        return ["runtime_classpath"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_distribution(jdk=True)

        if self.get_options().use_classpath_jars:
            # TODO: Make this work by capturing the correct Digest and passing them around the
            # right places.
            # See https://github.com/pantsbuild/pants/issues/6432
            raise TaskError("Hermetic javac execution currently doesn't work with classpath jars")

    def select(self, target):
        if not isinstance(target, JvmTarget):
            return False
        return target.has_sources(".java")

    def select_source(self, source_file_path):
        return source_file_path.endswith(".java")

    def javac_classpath(self):
        # Note that if this classpath is empty then Javac will automatically use the javac from
        # the JDK it was invoked with.
        return Java.global_javac_classpath(self.context.products)

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
        classpath = (ctx.classes_dir.path,) + tuple(ce.path for ce in dependency_classpath)

        if self.get_options().capture_classpath:
            self._record_compile_classpath(classpath, ctx.target, ctx.classes_dir.path)

        try:
            distribution = JvmPlatform.preferred_jvm_distribution([settings], strict=True)
        except DistributionLocator.Error:
            distribution = JvmPlatform.preferred_jvm_distribution([settings], strict=False)

        javac_args = []

        if settings.args:
            settings_args = settings.args
            if any("$JAVA_HOME" in a for a in settings.args):
                logger.debug(
                    'Substituting "$JAVA_HOME" with "{}" in jvm-platform args.'.format(
                        distribution.home
                    )
                )
                settings_args = (a.replace("$JAVA_HOME", distribution.home) for a in settings.args)
            javac_args.extend(settings_args)

            javac_args.extend(
                [
                    # TODO: support -release
                    "-source",
                    str(settings.source_level),
                    "-target",
                    str(settings.target_level),
                ]
            )

        if self.execution_strategy == self.ExecutionStrategy.hermetic:
            javac_args.extend(
                [
                    # We need to strip the source root from our output files. Outputting to a directory, and
                    # capturing that directory, does the job.
                    # Unfortunately, javac errors if the directory you pass to -d doesn't exist, and we don't
                    # have a convenient way of making a directory in the output tree, so let's just use the
                    # working directory as our output dir.
                    # This also has the benefit of not needing to strip leading directories from the returned
                    # snapshot.
                    "-d",
                    ".",
                ]
            )
        else:
            javac_args.extend(["-d", ctx.classes_dir.path])

        javac_args.extend(self._javac_plugin_args(javac_plugin_map))

        javac_args.extend(args)

        compiler_option_sets_args = self.get_merged_args_for_compiler_option_sets(
            compiler_option_sets
        )
        javac_args.extend(compiler_option_sets_args)

        javac_args.extend(["-classpath", ":".join(classpath)])
        javac_args.extend(ctx.sources)

        # From https://docs.oracle.com/javase/8/docs/technotes/tools/windows/javac.html#BHCJEIBB
        # Wildcards (*) aren’t allowed in these lists (such as for specifying *.java).
        # Use of the at sign (@) to recursively interpret files isn’t supported.
        # The -J options aren’t supported because they’re passed to the launcher,
        # which doesn’t support argument files.
        j_args = [j_arg for j_arg in javac_args if j_arg.startswith("-J")]
        safe_javac_args = list(filter(lambda x: x not in j_args, javac_args))

        with argfile.safe_args(safe_javac_args, self.get_options()) as batched_args:
            javac_cmd = [f"{distribution.real_home}/bin/javac"]
            javac_cmd.extend(j_args)
            javac_cmd.extend(batched_args)

            if self.execution_strategy == self.ExecutionStrategy.hermetic:
                self._execute_hermetic_compile(javac_cmd, ctx)
            else:
                with self.context.new_workunit(
                    name="javac", cmd=" ".join(javac_cmd), labels=[WorkUnitLabel.COMPILER]
                ) as workunit:
                    self.context.log.debug(f"Executing {' '.join(javac_cmd)}")
                    p = subprocess.Popen(
                        javac_cmd,
                        stdout=workunit.output("stdout"),
                        stderr=workunit.output("stderr"),
                    )
                    return_code = p.wait()
                    workunit.set_outcome(WorkUnit.FAILURE if return_code else WorkUnit.SUCCESS)
                    if return_code:
                        raise TaskError(f"javac exited with return code {return_code}")
                classes_directory = Path(ctx.classes_dir.path).relative_to(get_buildroot())
                self.context._scheduler.materialize_directory(
                    DirectoryToMaterialize(
                        self.post_compile_extra_resources_digest(
                            ctx, prepend_post_merge_relative_path=False
                        ),
                        path_prefix=str(classes_directory),
                    ),
                )

        self._create_context_jar(ctx)

    def _create_context_jar(self, compile_context):
        """Jar up the compile_context to its output jar location."""
        root = compile_context.classes_dir.path
        with compile_context.open_jar(mode="w") as jar:
            for abs_sub_dir, dirnames, filenames in safe_walk(root):
                for name in dirnames + filenames:
                    abs_filename = os.path.join(abs_sub_dir, name)
                    arcname = fast_relpath(abs_filename, root)
                    jar.write(abs_filename, arcname)

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
            ret.append(f"-Xplugin:{plugin} {' '.join(args)}")
        return ret

    def _execute_hermetic_compile(self, cmd, ctx):
        # For now, executing a compile remotely only works for targets that
        # do not have any dependencies or inner classes

        input_snapshot = ctx.target.sources_snapshot(scheduler=self.context._scheduler)
        output_files = tuple(
            # Assume no extra .class files to grab. We'll fix up that case soon.
            # Drop the source_root from the file path.
            # Assumes `-d .` has been put in the command.
            os.path.relpath(f.replace(".java", ".class"), ctx.target.target_base)
            for f in input_snapshot.files
            if f.endswith(".java")
        )

        process = Process(
            argv=tuple(cmd),
            input_files=input_snapshot.directory_digest,
            output_files=output_files,
            description=f"Compiling {ctx.target.address.spec} with javac",
        )
        exec_result = self.context.execute_process_synchronously_without_raising(
            process, "javac", (WorkUnitLabel.TASK, WorkUnitLabel.JVM),
        )

        # Dump the output to the .pants.d directory where it's expected by downstream tasks.
        merged_directories = self.context._scheduler.merge_directories(
            [
                exec_result.output_directory_digest,
                self.post_compile_extra_resources_digest(
                    ctx, prepend_post_merge_relative_path=False
                ),
            ]
        )
        classes_directory = Path(ctx.classes_dir.path).relative_to(get_buildroot())
        self.context._scheduler.materialize_directory(
            DirectoryToMaterialize(merged_directories, path_prefix=str(classes_directory)),
        )
