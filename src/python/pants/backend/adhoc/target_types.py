# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.core.util_rules.environments import EnvironmentField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    IntField,
    MultipleSourcesField,
    SpecialCasedDependencies,
    StringField,
    StringSequenceField,
    Target,
    ValidNumbers,
)
from pants.util.strutil import softwrap


class AdhocToolDependenciesField(Dependencies):
    pass


class AdhocToolRunnableField(StringField):
    alias = "runnable"
    required = True
    help = softwrap(
        """
        Address to a target that can be invoked by the `run` goal (and does not set
        `run_in_sandbox_behavior=NOT_SUPPORTED`). This will be executed along with any arguments
        specified by `argv`, in a sandbox with that target's transitive dependencies, along with
        the transitive dependencies specified by `execution_dependencies`.
        """
    )


class AdhocToolOutputFilesField(StringSequenceField):
    alias = "output_files"
    required = False
    default = ()
    help = softwrap(
        """
        Specify the shell command's output files to capture, relative to the value of `workdir`.

        For directories, use `output_directories`. At least one of `output_files` and
        `output_directories` must be specified.

        Relative paths (including `..`) may be used, as long as the path does not ascend further
        than the build root.
        """
    )


class AdhocToolOutputDirectoriesField(StringSequenceField):
    alias = "output_directories"
    required = False
    default = ()
    help = softwrap(
        """
        Specify full directories (including recursive descendants) of output to capture from the
        shell command, relative to the value of `workdir`.

        For individual files, use `output_files`. At least one of `output_files` and
        `output_directories` must be specified.

        Relative paths (including `..`) may be used, as long as the path does not ascend further
        than the build root.
        """
    )


class AdhocToolOutputDependenciesField(AdhocToolDependenciesField):
    supports_transitive_excludes = True
    alias = "output_dependencies"
    deprecated_alias = "dependencies"
    deprecated_alias_removal_version = "2.17.0.dev0"

    help = softwrap(
        """
        Any dependencies that the output artifacts require in order to be effectively consumed.

        To enable legacy use cases, if `execution_dependencies` is `None`, these dependencies will
        be materialized in the command execution sandbox. This behavior is deprecated, and will be
        removed in version 2.17.0.dev0.
        """
    )


class AdhocToolExecutionDependenciesField(SpecialCasedDependencies):
    alias = "execution_dependencies"
    required = False
    default = None

    help = softwrap(
        """
        The execution dependencies for this shell command.

        Dependencies specified here are those required to make the command complete successfully
        (e.g. file inputs, binaries compiled from other targets, etc), but NOT required to make
        the output side-effects useful. Dependencies that are required to use the side-effects
        produced by this command should be specified using the `output_dependencies` field.

        If this field is specified, dependencies from `output_dependencies` will not be added to
        the execution sandbox.
        """
    )


class AdhocToolSourcesField(MultipleSourcesField):
    # We solely register this field for codegen to work.
    alias = "_sources"
    uses_source_roots = False
    expected_num_files = 0


class AdhocToolArgumentsField(StringSequenceField):
    alias = "args"
    default = ()
    help = f"Extra arguments to pass into the `{AdhocToolRunnableField.alias}` field."


class AdhocToolStdoutFilenameField(StringField):
    alias = "stdout"
    default = None
    help = "A filename to capture the contents of `stdout` to, relative to the value of `workdir`."


class AdhocToolStderrFilenameField(StringField):
    alias = "stderr"
    default = None
    help = "A filename to capture the contents of `stdout` to, relative to the value of `workdir`."


class AdhocToolTimeoutField(IntField):
    alias = "timeout"
    default = 30
    help = "Command execution timeout (in seconds)."
    valid_numbers = ValidNumbers.positive_only


class AdhocToolExtraEnvVarsField(StringSequenceField):
    alias = "extra_env_vars"
    help = softwrap(
        """
        Additional environment variables to include in the shell process.
        Entries are strings in the form `ENV_VAR=value` to use explicitly; or just
        `ENV_VAR` to copy the value of a variable in Pants's own environment.
        """
    )


class AdhocToolLogOutputField(BoolField):
    alias = "log_output"
    default = False
    help = "Set to true if you want the output from the command logged to the console."


class AdhocToolWorkdirField(StringField):
    alias = "workdir"
    default = "."
    help = softwrap(
        "Sets the current working directory of the command. \n\n"
        "Values are relative to the build root, except in the following cases:\n\n"
        "* `.` specifies the location of the `BUILD` file.\n"
        "* Values beginning with `./` are relative to the location of the `BUILD` file.\n"
        "* `/` or the empty string specifies the build root.\n"
        "* Values beginning with `/` are also relative to the build root."
    )


class AdhocToolOutputRootDirField(StringField):
    alias = "root_output_directory"
    default = "/"
    help = softwrap(
        "Adjusts the location of files output by this command, when consumed as a dependency.\n\n"
        "Values are relative to the build root, except in the following cases:\n\n"
        "* `.` specifies the location of the `BUILD` file.\n"
        "* Values beginning with `./` are relative to the location of the `BUILD` file.\n"
        "* `/` or the empty string specifies the build root.\n"
        "* Values beginning with `/` are also relative to the build root."
    )


class AdhocToolTarget(Target):
    alias = "adhoc_tool"
    deprecated_alias = "experimental_run_in_sandbox"
    deprecated_alias_removal_version = "2.17.0.dev0"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        AdhocToolRunnableField,
        AdhocToolArgumentsField,
        AdhocToolExecutionDependenciesField,
        AdhocToolOutputDependenciesField,
        AdhocToolLogOutputField,
        AdhocToolOutputFilesField,
        AdhocToolOutputDirectoriesField,
        AdhocToolSourcesField,
        AdhocToolTimeoutField,
        AdhocToolExtraEnvVarsField,
        AdhocToolWorkdirField,
        AdhocToolOutputRootDirField,
        AdhocToolStdoutFilenameField,
        AdhocToolStderrFilenameField,
        EnvironmentField,
    )
    help = softwrap(
        """
        Execute any runnable target for its side effects.

        Example BUILD file:

            adhoc_tool(
                runnable=":python_source",
                argv=[""],
                tools=["tar", "curl", "cat", "bash", "env"],
                execution_dependencies=[":scripts"],
                outputs=["results/", "logs/my-script.log"],
            )

            shell_sources(name="scripts")
        """
    )
