# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from enum import Enum
from textwrap import dedent

from pants.backend.shell.shell_setup import ShellSetup
from pants.core.goals.test import RuntimePackageDependenciesField
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
    StringField,
    StringSequenceField,
    Target,
    TargetFilesGenerator,
    TargetFilesGeneratorSettings,
    TargetFilesGeneratorSettingsRequest,
    ValidNumbers,
    generate_file_based_overrides_field_help_message,
)
from pants.engine.unions import UnionRule
from pants.util.enums import match


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


class Shunit2TestDependenciesField(Dependencies):
    supports_transitive_excludes = True


class Shunit2TestTimeoutField(IntField):
    alias = "timeout"
    help = (
        "A timeout (in seconds) used by each test file belonging to this target.\n\n"
        "If unset, the test will never time out."
    )
    valid_numbers = ValidNumbers.positive_only


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
    help = (
        "A single test file for Bourne-based shell scripts using the shunit2 test framework.\n\n"
        "To use, add tests to your file per https://github.com/kward/shunit2/. Specify the shell "
        f"to run with by either setting the field `{Shunit2ShellField.alias}` or including a "
        f"shebang. To test the same file with multiple shells, create multiple `shunit2_tests` "
        f"targets, one for each shell.\n\n"
        f"Pants will automatically download the `shunit2` bash script and add "
        f"`source ./shunit2` to your test for you. If you already have `source ./shunit2`, "
        f"Pants will overwrite it to use the correct relative path."
    )


# -----------------------------------------------------------------------------------------------
# `shunit2_tests` target generator
# -----------------------------------------------------------------------------------------------


class Shunit2TestsGeneratorSourcesField(ShellGeneratingSourcesBase):
    default = ("*_test.sh", "test_*.sh", "tests.sh")


class Shunit2TestsOverrideField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        Shunit2TestTarget.alias,
        (
            "overrides={\n"
            '  "foo_test.sh": {"timeout": 120]},\n'
            '  "bar_test.sh": {"timeout": 200]},\n'
            '  ("foo_test.sh", "bar_test.sh"): {"tags": ["slow_tests"]},\n'
            "}"
        ),
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
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, ShellSourceField)
    help = "A single Bourne-based shell script, e.g. a Bash script."


class ShellSourcesGeneratingSourcesField(ShellGeneratingSourcesBase):
    default = ("*.sh",) + tuple(f"!{pat}" for pat in Shunit2TestsGeneratorSourcesField.default)


class ShellSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        ShellSourceTarget.alias,
        (
            "overrides={\n"
            '  "foo.sh": {"skip_shellcheck": True]},\n'
            '  "bar.sh": {"skip_shfmt": True]},\n'
            '  ("foo.sh", "bar.sh"): {"tags": ["linter_disabled"]},\n'
            "}"
        ),
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
    moved_fields = (Dependencies,)
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
    help = (
        "Specify the shell command output files and directories.\n\n"
        "Use a trailing slash on directory names, i.e. `my_dir/`."
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
    required = True
    help = (
        "Specify required executable tools that might be used.\n\n"
        "Only the tools explicitly provided will be available on the search PATH, "
        "and these tools must be found on the paths provided by "
        "[shell-setup].executable_search_paths (which defaults to the system PATH)."
    )


class ShellCommandLogOutputField(BoolField):
    alias = "log_output"
    default = False
    help = "Set to true if you want the output from the command logged to the console."


class ShellCommandRunWorkdirField(StringField):
    alias = "workdir"
    default = "."
    help = "Sets the current working directory of the command, relative to the project root."


class ShellCommandTarget(Target):
    alias = "experimental_shell_command"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        ShellCommandCommandField,
        ShellCommandLogOutputField,
        ShellCommandOutputsField,
        ShellCommandSourcesField,
        ShellCommandTimeoutField,
        ShellCommandToolsField,
    )
    help = (
        "Execute any external tool for its side effects.\n"
        + dedent(
            """\

            Example BUILD file:

                experimental_shell_command(
                  command="./my-script.sh --flag",
                  tools=["tar", "curl", "cat", "bash", "env"],
                  dependencies=[":scripts"],
                  outputs=["results/", "logs/my-script.log"],
                )

                shell_sources(name="scripts")

            """
        )
        + "Remember to add this target to the dependencies of each consumer, such as your "
        "`python_tests` or `docker_image`. When relevant, Pants will run your `command` and "
        "insert the `outputs` into that consumer's context.\n\n"
        "The command may be retried and/or cancelled, so ensure that it is idempotent."
    )


class ShellCommandRunTarget(Target):
    alias = "experimental_run_shell_command"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        ShellCommandCommandField,
        ShellCommandRunWorkdirField,
    )
    help = (
        "Run a script in the workspace, with all dependencies packaged/copied into a chroot.\n"
        + dedent(
            """\

            Example BUILD file:

                experimental_run_shell_command(
                  command="./scripts/my-script.sh --data-files-dir={chroot}",
                  dependencies=["src/project/files:data"],
                )

            """
        )
        + "The `command` may use either `{chroot}` on the command line, or the `$CHROOT` "
        "environment variable to get the root directory for where any dependencies are located.\n\n"
        "In contrast to the `experimental_shell_command`, in addition to `workdir` you only have "
        "the `command` and `dependencies` fields as the `tools` you are going to use are already "
        "on the PATH which is inherited from the Pants environment. Also, the `outputs` does not "
        "apply, as any output files produced will end up directly in your project tree."
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(TargetFilesGeneratorSettingsRequest, ShellGeneratorSettingsRequest),
    ]
