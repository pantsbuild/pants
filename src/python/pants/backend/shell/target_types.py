# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from enum import Enum

from pants.backend.shell.subsystems.shell_setup import ShellSetup
from pants.core.goals.test import RuntimePackageDependenciesField, TestTimeoutField
from pants.core.util_rules.environments import EnvironmentField
from pants.core.util_rules.system_binaries import BinaryPathTest
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    IntField,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    SpecialCasedDependencies,
    StringField,
    StringSequenceField,
    Target,
    TargetFilesGenerator,
    TargetFilesGeneratorSettings,
    TargetFilesGeneratorSettingsRequest,
    ValidNumbers,
    generate_file_based_overrides_field_help_message,
    generate_multiple_sources_field_help_message,
)
from pants.engine.unions import UnionRule
from pants.util.enums import match
from pants.util.strutil import softwrap


class ShellDependenciesField(Dependencies):
    pass


class ShellSourceField(SingleSourceField):
    # Normally, we would add `expected_file_extensions = ('.sh',)`, but Bash scripts don't need a
    # file extension, so we don't use this.
    uses_source_roots = False


class ShellGeneratingSourcesBase(MultipleSourcesField):
    uses_source_roots = False


class ShellGeneratorSettingsRequest(TargetFilesGeneratorSettingsRequest):
    pass


@rule
def generator_settings(
    _: ShellGeneratorSettingsRequest,
    shell_setup: ShellSetup,
) -> TargetFilesGeneratorSettings:
    return TargetFilesGeneratorSettings(
        add_dependencies_on_all_siblings=not shell_setup.dependency_inference
    )


# -----------------------------------------------------------------------------------------------
# `shunit2_test` target
# -----------------------------------------------------------------------------------------------


class Shunit2Shell(Enum):
    sh = "sh"
    bash = "bash"
    dash = "dash"
    ksh = "ksh"
    pdksh = "pdksh"
    zsh = "zsh"

    @classmethod
    def parse_shebang(cls, shebang: bytes) -> Shunit2Shell | None:
        if not shebang:
            return None
        first_line = shebang.splitlines()[0]
        matches = re.match(rb"^#! *[/\w]*/(?P<program>\w+) *(?P<arg>\w*)", first_line)
        if not matches:
            return None
        program = matches.group("program")
        if program == b"env":
            program = matches.group("arg")
        try:
            return cls(program.decode())
        except ValueError:
            return None

    @property
    def binary_path_test(self) -> BinaryPathTest | None:
        arg = match(  # type: ignore[misc]
            self,
            {
                self.sh: None,
                self.bash: "--version",
                self.dash: None,
                self.ksh: "--version",
                self.pdksh: None,
                self.zsh: "--version",
            },
        )
        if not arg:
            return None
        return BinaryPathTest((arg,))


class Shunit2TestDependenciesField(ShellDependenciesField):
    supports_transitive_excludes = True


class Shunit2TestTimeoutField(TestTimeoutField):
    pass


class SkipShunit2TestsField(BoolField):
    alias = "skip_tests"
    default = False
    help = "If true, don't run this target's tests."


class Shunit2TestSourceField(ShellSourceField):
    pass


class Shunit2ShellField(StringField):
    alias = "shell"
    valid_choices = Shunit2Shell
    help = "Which shell to run the tests with. If unspecified, Pants will look for a shebang line."


class Shunit2TestTarget(Target):
    alias = "shunit2_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Shunit2TestSourceField,
        Shunit2TestDependenciesField,
        Shunit2TestTimeoutField,
        SkipShunit2TestsField,
        Shunit2ShellField,
        RuntimePackageDependenciesField,
    )
    help = softwrap(
        f"""
        A single test file for Bourne-based shell scripts using the shunit2 test framework.

        To use, add tests to your file per https://github.com/kward/shunit2/. Specify the shell
        to run with by either setting the field `{Shunit2ShellField.alias}` or including a
        shebang. To test the same file with multiple shells, create multiple `shunit2_tests`
        targets, one for each shell.

        Pants will automatically download the `shunit2` bash script and add
        `source ./shunit2` to your test for you. If you already have `source ./shunit2`,
        Pants will overwrite it to use the correct relative path.
        """
    )


# -----------------------------------------------------------------------------------------------
# `shunit2_tests` target generator
# -----------------------------------------------------------------------------------------------


class Shunit2TestsGeneratorSourcesField(ShellGeneratingSourcesBase):
    default = ("*_test.sh", "test_*.sh", "tests.sh")
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['test.sh', 'test_*.sh', '!test_ignore.sh']`"
    )


class Shunit2TestsOverrideField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        Shunit2TestTarget.alias,
        """
        overrides={
            "foo_test.sh": {"timeout": 120},
            "bar_test.sh": {"timeout": 200},
            ("foo_test.sh", "bar_test.sh"): {"tags": ["slow_tests"]},
        }
        """,
    )


class Shunit2TestsGeneratorTarget(TargetFilesGenerator):
    alias = "shunit2_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Shunit2TestsGeneratorSourcesField,
        Shunit2TestsOverrideField,
    )
    generated_target_cls = Shunit2TestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        Shunit2TestDependenciesField,
        Shunit2TestTimeoutField,
        SkipShunit2TestsField,
        Shunit2ShellField,
        RuntimePackageDependenciesField,
    )
    help = "Generate a `shunit2_test` target for each file in the `sources` field."


# -----------------------------------------------------------------------------------------------
# `shell_source` and `shell_sources` targets
# -----------------------------------------------------------------------------------------------


class ShellSourceTarget(Target):
    alias = "shell_source"
    core_fields = (*COMMON_TARGET_FIELDS, ShellDependenciesField, ShellSourceField)
    help = "A single Bourne-based shell script, e.g. a Bash script."


class ShellSourcesGeneratingSourcesField(ShellGeneratingSourcesBase):
    default = ("*.sh",) + tuple(f"!{pat}" for pat in Shunit2TestsGeneratorSourcesField.default)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.sh', 'new_*.sh', '!old_ignore.sh']`"
    )


class ShellSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        ShellSourceTarget.alias,
        """
        overrides={
            "foo.sh": {"skip_shellcheck": True]},
            "bar.sh": {"skip_shfmt": True]},
            ("foo.sh", "bar.sh"): {"tags": ["linter_disabled"]},
        }
        """,
    )


class ShellSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "shell_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ShellSourcesGeneratingSourcesField,
        ShellSourcesOverridesField,
    )
    generated_target_cls = ShellSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (ShellDependenciesField,)
    help = "Generate a `shell_source` target for each file in the `sources` field."


# -----------------------------------------------------------------------------------------------
# `shell_command` target
# -----------------------------------------------------------------------------------------------


class ShellCommandCommandField(StringField):
    alias = "command"
    required = True
    help = "Shell command to execute.\n\nThe command is executed as 'bash -c <command>' by default."


class ShellCommandOutputsField(StringSequenceField):
    alias = "outputs"
    help = softwrap(
        """
        Specify the shell command output files and directories.

        Use a trailing slash on directory names, i.e. `my_dir/`.
        """
    )
    removal_hint = "To fix, use `output_files` and `output_directories` instead."
    removal_version = "2.17.0.dev0"


class ShellCommandOutputFilesField(StringSequenceField):
    alias = "output_files"
    required = False
    default = ()
    help = softwrap(
        """
        Specify the shell command's output files to capture.

        For directories, use `output_directories`. At least one of `output_files` and
        `output_directories` must be specified.
        """
    )


class ShellCommandOutputDirectoriesField(StringSequenceField):
    alias = "output_directories"
    help = softwrap(
        """
        Specify full directories of output from the shell command to capture.

        For files, use `output_files`. At least one of `output_files` and
        `output_directories` must be specified.
        """
    )


class ShellCommandDependenciesField(ShellDependenciesField):
    supports_transitive_excludes = True


class ShellCommandUseOutputDependenciesInRuntimeField(BoolField):
    alias = "use_dependencies_at_runtime"
    default = True
    help = softwrap(
        """
        Allows you to separate dependencies between those required to run the shell command and
        those required to successfully use the output artifacts.

        If `True`, the dependencies specified in the `dependencies` field will be materialized
        into the runtime sandbox (with any package dependencies built), and also included in any
        transitive dependency resolution involving this target. Dependencies specified in
        `runtime_dependencies` will also be materialized into the sandbox.

        If `False`, the dependencies in the `dependencies` field will only be used for transitive
        dependency resolution, and only the `runtime_dependencies` field will be materialized into
        the sandbox.
        """
    )


class ShellCommandRuntimeDependenciesField(SpecialCasedDependencies):
    alias = "runtime_dependencies"
    help = softwrap(
        """
        The runtime dependencies for this shell command.

        Dependencies specified here are those required to make the command complete successfully
        (e.g. file inputs, binaries compiled from other targets, etc), but NOT required to make
        the output side-effects useful. Dependencies that are required to use the side-effects
        produced by this command should be specified using the `dependencies` field.

        If you have fully separated your dependencies between runtime and output dependencies,
        you can set `use_dependencies_at_runtime = False`.
        """
    )


class ShellCommandSourcesField(MultipleSourcesField):
    # We solely register this field for codegen to work.
    alias = "_sources"
    uses_source_roots = False
    expected_num_files = 0


class ShellCommandTimeoutField(IntField):
    alias = "timeout"
    default = 30
    help = "Command execution timeout (in seconds)."
    valid_numbers = ValidNumbers.positive_only


class ShellCommandToolsField(StringSequenceField):
    alias = "tools"
    default = ()
    help = softwrap(
        """
        Specify required executable tools that might be used.

        Only the tools explicitly provided will be available on the search PATH,
        and these tools must be found on the paths provided by
        [shell-setup].executable_search_paths (which defaults to the system PATH).
        """
    )


class ShellCommandExtraEnvVarsField(StringSequenceField):
    alias = "extra_env_vars"
    help = softwrap(
        """
        Additional environment variables to include in the shell process.
        Entries are strings in the form `ENV_VAR=value` to use explicitly; or just
        `ENV_VAR` to copy the value of a variable in Pants's own environment.
        """
    )


class ShellCommandLogOutputField(BoolField):
    alias = "log_output"
    default = False
    help = "Set to true if you want the output from the command logged to the console."


class ShellCommandRunWorkdirField(StringField):
    alias = "workdir"
    default = "."
    help = "Sets the current working directory of the command, relative to the project root."


class ShellCommandTestDependenciesField(ShellCommandDependenciesField):
    pass


class SkipShellCommandTestsField(BoolField):
    alias = "skip_tests"
    default = False
    help = "If true, don't run this tests for target."


class ShellCommandTarget(Target):
    alias = "experimental_shell_command"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ShellCommandDependenciesField,
        ShellCommandRuntimeDependenciesField,
        ShellCommandUseOutputDependenciesInRuntimeField,
        ShellCommandCommandField,
        ShellCommandLogOutputField,
        ShellCommandOutputsField,
        ShellCommandOutputFilesField,
        ShellCommandOutputDirectoriesField,
        ShellCommandSourcesField,
        ShellCommandTimeoutField,
        ShellCommandToolsField,
        ShellCommandExtraEnvVarsField,
        EnvironmentField,
    )
    help = softwrap(
        """
        Execute any external tool for its side effects.

        Example BUILD file:

            experimental_shell_command(
                command="./my-script.sh --flag",
                tools=["tar", "curl", "cat", "bash", "env"],
                dependencies=[":scripts"],
                output_files=["logs/my-script.log"],
                output_directories=["results"],
            )

            shell_sources(name="scripts")

        Remember to add this target to the dependencies of each consumer, such as your
        `python_tests` or `docker_image`. When relevant, Pants will run your `command` and
        insert the `outputs` into that consumer's context.

        The command may be retried and/or cancelled, so ensure that it is idempotent.
        """
    )


class ShellCommandRunTarget(Target):
    alias = "experimental_run_shell_command"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ShellCommandDependenciesField,
        ShellCommandCommandField,
        ShellCommandRunWorkdirField,
    )
    help = softwrap(
        """
        Run a script in the workspace, with all dependencies packaged/copied into a chroot.

        Example BUILD file:

            experimental_run_shell_command(
                command="./scripts/my-script.sh --data-files-dir={chroot}",
                dependencies=["src/project/files:data"],
            )

        The `command` may use either `{chroot}` on the command line, or the `$CHROOT`
        environment variable to get the root directory for where any dependencies are located.

        In contrast to the `experimental_shell_command`, in addition to `workdir` you only have
        the `command` and `dependencies` fields as the `tools` you are going to use are already
        on the PATH which is inherited from the Pants environment. Also, the `outputs` does not
        apply, as any output files produced will end up directly in your project tree.
        """
    )


class ShellCommandTestTarget(Target):
    alias = "experimental_test_shell_command"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ShellCommandTestDependenciesField,
        ShellCommandCommandField,
        ShellCommandLogOutputField,
        ShellCommandSourcesField,
        ShellCommandTimeoutField,
        ShellCommandToolsField,
        ShellCommandExtraEnvVarsField,
        EnvironmentField,
        SkipShellCommandTestsField,
    )
    help = softwrap(
        """
        Run a script as a test via the `test` goal, with all dependencies packaged/copied available in the chroot.

        Example BUILD file:

            experimental_test_shell_command(
                name="test",
                tools=["test"],
                command="test -r $CHROOT/some-data-file.txt",
                dependencies=["src/project/files:data"],
            )

        The `command` may use either `{chroot}` on the command line, or the `$CHROOT`
        environment variable to get the root directory for where any dependencies are located.

        In contrast to the `experimental_run_shell_command`, this target is intended to run shell commands as tests
        and will only run them via the `test` goal.
        """
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(TargetFilesGeneratorSettingsRequest, ShellGeneratorSettingsRequest),
    ]
