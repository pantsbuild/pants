# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import abstractmethod

from pants.backend.jvm.subsystems.scalafmt import Scalafmt
from pants.backend.jvm.tasks.rewrite_base import RewriteBase
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.lint_task_mixin import LintTaskMixin


class ScalafmtTask(RewriteBase):
    """Abstract class to run ScalaFmt commands.

    Classes that inherit from this should override additional_args and process_result to run
    different scalafmt commands.
    """

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (Scalafmt,)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        cls.register_jvm_tool(
            register,
            "scalafmt",
            classpath=[JarDependency(org="com.geirsson", name="scalafmt-cli_2.11", rev="1.5.1")],
        )

    @classmethod
    def target_types(cls):
        return ["scala_library", "junit_tests"]

    @classmethod
    def source_extension(cls):
        return ".scala"

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("ScalaFmt", 5)]

    def invoke_tool(self, absolute_root, target_sources):
        args = list(self.additional_args)
        config = Scalafmt.global_instance().options.config
        if config is not None:
            args.extend(["--config", config])
        args.extend([source for _target, source in target_sources])

        return self.runjava(
            classpath=self.tool_classpath("scalafmt"),
            main="org.scalafmt.cli.Cli",
            args=args,
            workunit_name="scalafmt",
            jvm_options=self.get_options().jvm_options,
        )

    @property
    @abstractmethod
    def additional_args(self):
        """Returns the arguments used to run Scalafmt command.

        The return value should be an array of strings.  For example, to run the Scalafmt help
        command: ['--help']
        """


class ScalaFmtCheckFormat(LintTaskMixin, ScalafmtTask):
    """This Task checks that all scala files in the target are formatted correctly.

    If the files are not formatted correctly an error is raised
    including the command to run to format the files correctly

    :API: public
    """

    sideeffecting = False
    additional_args = ["--test"]

    @property
    def skip_execution(self):
        return Scalafmt.global_instance().options.skip

    def process_result(self, result):
        if result != 0:
            raise TaskError(
                "Scalafmt failed with exit code {}; to fix run: "
                "`./pants fmt <targets>`".format(result),
                exit_code=result,
            )


class ScalaFmtFormat(FmtTaskMixin, ScalafmtTask):
    """This Task reads all scala files in the target and emits the source in a standard style as
    specified by the configuration file.

    This task mutates the underlying flies.

    :API: public
    """

    sideeffecting = True
    additional_args = ["-i"]

    @property
    def skip_execution(self):
        return super().determine_if_skipped(formatter_subsystem=Scalafmt.global_instance())

    def process_result(self, result):
        # Processes the results of running the scalafmt command.
        if result != 0:
            raise TaskError("Scalafmt failed to format files", exit_code=result)
