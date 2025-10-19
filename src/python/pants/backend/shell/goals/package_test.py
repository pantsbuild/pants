# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.shell.goals import package as shell_package
from pants.backend.shell.target_types import ShellCommandPackageTarget, ShellSourcesGeneratorTarget
from pants.build_graph.address import Address
from pants.core.goals import package
from pants.core.goals.package import BuiltPackage, OutputPathField
from pants.core.util_rules import source_files, system_binaries
from pants.engine.fs import DigestContents
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *shell_package.rules(),
            *source_files.rules(),
            *package.rules(),
            *system_binaries.rules(),
            QueryRule(BuiltPackage, (shell_package.PackageShellCommandFieldSet,)),
        ],
        target_types=[
            ShellSourcesGeneratorTarget,
            ShellCommandPackageTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


@pytest.mark.platform_specific_behavior
def test_basic_package_shell_command(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                package_shell_command(
                  name="build",
                  command="echo 'Hello, World!' > output.txt",
                  tools=["echo"],
                  output_files=["output.txt"],
                  packaged_artifacts=["output.txt"],
                  output_path="",
                )
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="build"))
    field_set = shell_package.PackageShellCommandFieldSet.create(tgt)

    built_package = rule_runner.request(BuiltPackage, [field_set])

    assert built_package.digest
    digest_contents = rule_runner.request(DigestContents, [built_package.digest])
    assert len(digest_contents) == 1
    assert digest_contents[0].path == "output.txt"
    assert digest_contents[0].content == b"Hello, World!\n"


@pytest.mark.platform_specific_behavior
def test_package_shell_command_with_multiple_outputs(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                package_shell_command(
                  name="build",
                  command="echo 'file1' > output1.txt && echo 'file2' > output2.txt",
                  tools=["echo"],
                  output_files=["output1.txt", "output2.txt"],
                  packaged_artifacts=["output1.txt", "output2.txt"],
                  output_path="",
                )
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="build"))
    field_set = shell_package.PackageShellCommandFieldSet.create(tgt)

    built_package = rule_runner.request(BuiltPackage, [field_set])

    assert built_package.digest
    digest_contents = rule_runner.request(DigestContents, [built_package.digest])
    assert len(digest_contents) == 2
    # Sort by path for deterministic testing
    sorted_contents = sorted(digest_contents, key=lambda x: x.path)
    assert sorted_contents[0].path == "output1.txt"
    assert sorted_contents[0].content == b"file1\n"
    assert sorted_contents[1].path == "output2.txt"
    assert sorted_contents[1].content == b"file2\n"


@pytest.mark.platform_specific_behavior
def test_package_shell_command_with_output_directories(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                package_shell_command(
                  name="build",
                  command="mkdir -p dist && echo 'content' > dist/file.txt",
                  tools=["mkdir", "echo"],
                  output_directories=["dist"],
                  packaged_artifacts=["dist"],
                  output_path="",
                )
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="build"))
    field_set = shell_package.PackageShellCommandFieldSet.create(tgt)

    built_package = rule_runner.request(BuiltPackage, [field_set])

    assert built_package.digest
    digest_contents = rule_runner.request(DigestContents, [built_package.digest])
    assert len(digest_contents) == 1
    assert digest_contents[0].path == "dist/file.txt"
    assert digest_contents[0].content == b"content\n"


@pytest.mark.platform_specific_behavior
def test_package_shell_command_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                package_shell_command(
                  name="build",
                  command="echo test > output.txt",
                  tools=["echo"],
                  output_files=["output.txt"],
                  packaged_artifacts=["output.txt"],
                  skip_package=True,
                )
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="build"))
    assert shell_package.PackageShellCommandFieldSet.opt_out(tgt)


@pytest.mark.platform_specific_behavior
def test_outputs_match_mode_support(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                package_shell_command(
                    name="all_with_present_file",
                    command="touch some-file",
                    tools=["touch"],
                    output_files=["some-file"],
                    output_directories=["some-directory"],
                    outputs_match_mode="all",
                    packaged_artifacts=["some-file"],
                    output_path="",
                )
                package_shell_command(
                    name="all_with_present_directory",
                    command="mkdir some-directory",
                    tools=["mkdir"],
                    output_files=["some-file"],
                    output_directories=["some-directory"],
                    outputs_match_mode="all",
                    packaged_artifacts=["some-file"],
                    output_path="",
                )
                package_shell_command(
                    name="at_least_one_with_present_file",
                    command="touch some-file",
                    tools=["touch"],
                    output_files=["some-file"],
                    output_directories=["some-directory"],
                    outputs_match_mode="at_least_one",
                    packaged_artifacts=["some-file"],
                    output_path="",
                )
                package_shell_command(
                    name="at_least_one_with_present_directory",
                    command="mkdir some-directory && touch some-directory/foo.txt",
                    tools=["mkdir", "touch"],
                    output_files=["some-file"],
                    output_directories=["some-directory"],
                    outputs_match_mode="at_least_one",
                    packaged_artifacts=["some-directory"],
                    output_path="",
                )
                """
            )
        }
    )

    def run_package(address: Address) -> BuiltPackage:
        tgt = rule_runner.get_target(address)
        field_set = shell_package.PackageShellCommandFieldSet.create(tgt)
        return rule_runner.request(BuiltPackage, [field_set])

    def assert_package_result(
        address: Address,
        expected_files: set[str],
    ) -> None:
        package_result = run_package(address)
        if expected_files:
            contents = rule_runner.request(DigestContents, [package_result.digest])
            assert {fc.path for fc in contents} == expected_files
        else:
            # Empty digest case
            contents = rule_runner.request(DigestContents, [package_result.digest])
            assert len(contents) == 0

    # Test all mode with missing directory - should fail
    with pytest.raises(ExecutionError) as exc_info:
        run_package(Address("", target_name="all_with_present_file"))
    assert "some-directory" in str(exc_info.value)

    # Test all mode with missing file - should fail
    with pytest.raises(ExecutionError) as exc_info:
        run_package(Address("", target_name="all_with_present_directory"))
    assert "some-file" in str(exc_info.value)

    # Test at_least_one mode with present file - should succeed
    assert_package_result(Address("", target_name="at_least_one_with_present_file"), {"some-file"})

    # Test at_least_one mode with present directory - should succeed
    assert_package_result(
        Address("", target_name="at_least_one_with_present_directory"),
        {"some-directory/foo.txt"},
    )


def test_output_path_field(rule_runner: RuleRunner) -> None:
    """Test the output_path field template behavior."""
    rule_runner.write_files(
        {
            "src/foo/BUILD": dedent(
                """\
                package_shell_command(
                    name="default",
                    command="echo test",
                    tools=["echo"],
                    output_files=["output.txt"],
                    packaged_artifacts=["output.txt"],
                )
                package_shell_command(
                    name="no-template",
                    command="echo test",
                    tools=["echo"],
                    output_files=["output.txt"],
                    output_path="custom/path",
                    packaged_artifacts=["output.txt"],
                )
                package_shell_command(
                    name="with-spec-path",
                    command="echo test",
                    tools=["echo"],
                    output_files=["output.txt"],
                    output_path="${spec_path_normalized}/custom",
                    packaged_artifacts=["output.txt"],
                )
                package_shell_command(
                    name="with-target-name",
                    command="echo test",
                    tools=["echo"],
                    output_files=["output.txt"],
                    output_path="build/${target_name_normalized}",
                    packaged_artifacts=["output.txt"],
                )
                """
            )
        }
    )

    def get_output_path(target_name: str, *, file_ending: str | None = None) -> str:
        tgt = rule_runner.get_target(Address("src/foo", target_name=target_name))
        output_path_field = tgt.get(OutputPathField)
        return output_path_field.value_or_default(file_ending=file_ending)

    # Test default template behavior
    output_path_default = get_output_path("default")
    assert output_path_default == "src.foo/default"

    # Test no template - custom path
    output_path_no_template = get_output_path("no-template")
    assert output_path_no_template == "custom/path"

    # Test with spec_path_normalized
    output_path_with_spec = get_output_path("with-spec-path")
    assert output_path_with_spec == "src.foo/custom"

    # Test with target_name_normalized
    output_path_with_target = get_output_path("with-target-name")
    assert output_path_with_target == "build/with-target-name"


def test_close_over_parent_paths() -> None:
    assert shell_package._close_over_parent_paths(["a/b/c", "d"]) == frozenset(
        ["a", "a/b", "a/b/c", "d"]
    )
