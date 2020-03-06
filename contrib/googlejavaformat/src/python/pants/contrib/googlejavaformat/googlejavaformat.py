# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import abstractmethod

from pants.backend.jvm.tasks.rewrite_base import RewriteBase
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.lint_task_mixin import LintTaskMixin

from pants.contrib.googlejavaformat.subsystem import GoogleJavaFormat


class GoogleJavaFormatBase(RewriteBase):
    def _resolve_conflicting_skip(self, *, old_scope: str):
        # Skip mypy because this is a temporary hack, and mypy doesn't follow the inheritance chain
        # properly.
        return self.resolve_conflicting_skip_options(  # type: ignore
            old_scope=old_scope,
            new_scope="google-java-format",
            subsystem=GoogleJavaFormat.global_instance(),
        )

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        cls.register_jvm_tool(
            register,
            "google-java-format",
            classpath=[
                JarDependency(
                    org="com.google.googlejavaformat", name="google-java-format", rev="1.5"
                )
            ],
        )

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("GoogleJavaFormatBase", 1)]

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (GoogleJavaFormat,)

    @classmethod
    def target_types(cls):
        return ["java_library", "junit_tests"]

    @classmethod
    def source_extension(cls):
        return ".java"

    def invoke_tool(self, _, target_sources):
        args = list(self.additional_args)
        args.extend([source for target, source in target_sources])
        return self.runjava(
            classpath=self.tool_classpath("google-java-format"),
            main="com.google.googlejavaformat.java.Main",
            args=args,
            workunit_name="google-java-format",
            jvm_options=self.get_options().jvm_options,
        )

    @property
    @abstractmethod
    def additional_args(self):
        """List of additional args to supply on the tool command-line."""


class GoogleJavaFormatLintTask(LintTaskMixin, GoogleJavaFormatBase):
    """Check if Java source code complies with Google Java Style.

    If the files are not formatted correctly an error is raised including the command to run to
    format the files correctly
    """

    sideeffecting = False
    additional_args = ["--set-exit-if-changed"]

    @property
    def skip_execution(self):
        return GoogleJavaFormat.global_instance().options.skip

    def process_result(self, result):
        if result != 0:
            raise TaskError(
                "google-java-format failed with exit code {}; to fix run: "
                "`./pants fmt <targets>`".format(result),
                exit_code=result,
            )


class GoogleJavaFormatTask(FmtTaskMixin, GoogleJavaFormatBase):
    """Reformat Java source code to comply with Google Java Style."""

    sideeffecting = True
    additional_args = ["-i"]

    @property
    def skip_execution(self):
        return super().determine_if_skipped(formatter_subsystem=GoogleJavaFormat.global_instance())

    def process_result(self, result):
        if result != 0:
            raise TaskError("google-java-format failed to format files", exit_code=result)
