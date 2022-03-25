# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.util_rules import pex
from pants.core.goals.update_build_files import (
    FormatWithBlackRequest,
    FormatWithYapfRequest,
    RenameDeprecatedFieldsRequest,
    RenameDeprecatedTargetsRequest,
    RenamedFieldTypes,
    RenamedTargetTypes,
    RewrittenBuildFile,
    RewrittenBuildFileRequest,
    UpdateBuildFilesGoal,
    UpdateBuildFilesSubsystem,
    determine_renamed_field_types,
    format_build_file_with_black,
    format_build_file_with_yapf,
    maybe_rename_deprecated_fields,
    maybe_rename_deprecated_targets,
    update_build_files,
)
from pants.core.util_rules import config_files
from pants.engine.rules import SubsystemRule, rule
from pants.engine.target import RegisteredTargetTypes, StringField, Target, TargetGenerator
from pants.engine.unions import UnionMembership, UnionRule
from pants.testutil.rule_runner import GoalRuleResult, RuleRunner
from pants.util.frozendict import FrozenDict

# ------------------------------------------------------------------------------------------
# Generic goal
# ------------------------------------------------------------------------------------------


class MockRewriteAddLine(RewrittenBuildFileRequest):
    pass


class MockRewriteReverseLines(RewrittenBuildFileRequest):
    pass


@rule
def add_line(request: MockRewriteAddLine) -> RewrittenBuildFile:
    return RewrittenBuildFile(
        request.path, (*request.lines, "added line"), change_descriptions=("Add a new line",)
    )


@rule
def reverse_lines(request: MockRewriteReverseLines) -> RewrittenBuildFile:
    return RewrittenBuildFile(
        request.path, tuple(reversed(request.lines)), change_descriptions=("Reverse lines",)
    )


@pytest.fixture
def generic_goal_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=(
            update_build_files,
            add_line,
            reverse_lines,
            SubsystemRule(UpdateBuildFilesSubsystem),
            UnionRule(RewrittenBuildFileRequest, MockRewriteAddLine),
            UnionRule(RewrittenBuildFileRequest, MockRewriteReverseLines),
        )
    )


def test_goal_rewrite_mode(generic_goal_rule_runner: RuleRunner) -> None:
    """Checks that we correctly write the changes and pipe fixers to each other."""
    generic_goal_rule_runner.write_files({"BUILD": "line\n", "dir/BUILD": "line 1\nline 2\n"})
    result = generic_goal_rule_runner.run_goal_rule(UpdateBuildFilesGoal)
    assert result.exit_code == 0
    assert result.stdout == dedent(
        """\
        Updated BUILD:
          - Add a new line
          - Reverse lines
        Updated dir/BUILD:
          - Add a new line
          - Reverse lines
        """
    )
    assert Path(generic_goal_rule_runner.build_root, "BUILD").read_text() == "added line\nline\n"
    assert (
        Path(generic_goal_rule_runner.build_root, "dir/BUILD").read_text()
        == "added line\nline 2\nline 1\n"
    )


def test_goal_check_mode(generic_goal_rule_runner: RuleRunner) -> None:
    """Checks that we correctly set the exit code and pipe fixers to each other."""
    generic_goal_rule_runner.write_files({"BUILD": "line\n", "dir/BUILD": "line 1\nline 2\n"})
    result = generic_goal_rule_runner.run_goal_rule(
        UpdateBuildFilesGoal, global_args=["--pants-bin-name=./custom_pants"], args=["--check"]
    )
    assert result.exit_code == 1
    assert result.stdout == dedent(
        """\
        Would update BUILD:
          - Add a new line
          - Reverse lines
        Would update dir/BUILD:
          - Add a new line
          - Reverse lines

        To fix `update-build-files` failures, run `./custom_pants update-build-files`.
        """
    )
    assert Path(generic_goal_rule_runner.build_root, "BUILD").read_text() == "line\n"
    assert Path(generic_goal_rule_runner.build_root, "dir/BUILD").read_text() == "line 1\nline 2\n"


# ------------------------------------------------------------------------------------------
# Black formatter fixer
# ------------------------------------------------------------------------------------------

# See black/rules_integration_test.py for why we set LANG and LC_ALL.
BLACK_ENV_INHERIT = {"PATH", "PYENV_ROOT", "HOME", "LANG", "LC_ALL"}


@pytest.fixture
def black_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=(
            format_build_file_with_black,
            update_build_files,
            *config_files.rules(),
            *pex.rules(),
            SubsystemRule(Black),
            SubsystemRule(UpdateBuildFilesSubsystem),
            UnionRule(RewrittenBuildFileRequest, FormatWithBlackRequest),
        )
    )


def test_black_fixer_fixes(black_rule_runner: RuleRunner) -> None:
    black_rule_runner.write_files({"BUILD": "tgt( name =  't' )"})
    result = black_rule_runner.run_goal_rule(UpdateBuildFilesGoal, env_inherit=BLACK_ENV_INHERIT)
    assert result.exit_code == 0
    assert result.stdout == dedent(
        """\
        Updated BUILD:
          - Format with Black
        """
    )
    assert Path(black_rule_runner.build_root, "BUILD").read_text() == 'tgt(name="t")\n'


def test_black_fixer_noops(black_rule_runner: RuleRunner) -> None:
    black_rule_runner.write_files({"BUILD": 'tgt(name="t")\n'})
    result = black_rule_runner.run_goal_rule(UpdateBuildFilesGoal, env_inherit=BLACK_ENV_INHERIT)
    assert result.exit_code == 0
    assert Path(black_rule_runner.build_root, "BUILD").read_text() == 'tgt(name="t")\n'


def test_black_fixer_args(black_rule_runner: RuleRunner) -> None:
    black_rule_runner.write_files({"BUILD": "tgt(name='t')\n"})
    result = black_rule_runner.run_goal_rule(
        UpdateBuildFilesGoal,
        global_args=["--black-args='--skip-string-normalization'"],
        env_inherit=BLACK_ENV_INHERIT,
    )
    assert result.exit_code == 0
    assert Path(black_rule_runner.build_root, "BUILD").read_text() == "tgt(name='t')\n"


def test_black_config(black_rule_runner: RuleRunner) -> None:
    black_rule_runner.write_files(
        {
            "pyproject.toml": "[tool.black]\nskip-string-normalization = 'true'\n",
            "BUILD": "tgt(name='t')\n",
        },
    )
    result = black_rule_runner.run_goal_rule(UpdateBuildFilesGoal, env_inherit=BLACK_ENV_INHERIT)
    assert result.exit_code == 0
    assert Path(black_rule_runner.build_root, "BUILD").read_text() == "tgt(name='t')\n"


# ------------------------------------------------------------------------------------------
# Yapf formatter fixer
# ------------------------------------------------------------------------------------------


def run_yapf(
    build_content: str, *, extra_args: list[str] | None = None
) -> tuple[GoalRuleResult, str]:
    """Returns the Goal's result and contents of the BUILD file after execution."""
    rule_runner = RuleRunner(
        rules=(
            format_build_file_with_yapf,
            update_build_files,
            *config_files.rules(),
            *pex.rules(),
            SubsystemRule(Yapf),
            SubsystemRule(UpdateBuildFilesSubsystem),
            UnionRule(RewrittenBuildFileRequest, FormatWithYapfRequest),
        )
    )
    rule_runner.write_files({"BUILD": build_content})
    goal_result = rule_runner.run_goal_rule(
        UpdateBuildFilesGoal,
        args=["--update-build-files-formatter=yapf"],
        global_args=extra_args or (),
        env_inherit=BLACK_ENV_INHERIT,
    )
    rewritten_build = Path(rule_runner.build_root, "BUILD").read_text()
    return goal_result, rewritten_build


def test_yapf_fixer_fixes() -> None:
    result, build = run_yapf("tgt( name =  't' )")
    assert result.exit_code == 0
    assert result.stdout == dedent(
        """\
        Updated BUILD:
          - Format with Yapf
        """
    )
    assert build == "tgt(name='t')\n"


def test_yapf_fixer_noops() -> None:
    result, build = run_yapf('tgt(name="t")\n')
    assert result.exit_code == 0
    assert not result.stdout
    assert build == 'tgt(name="t")\n'


# ------------------------------------------------------------------------------------------
# Renamed target types fixer
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lines",
    (
        # Already valid.
        ["new_name()"],
        ["new_name ( ) "],
        ["new_name(foo)"],
        ["new_name(", "", ")"],
        # Unrelated lines.
        ["", "123", "target()", "name='new_name'"],
        # Ignore indented
        ["  new_name()"],
    ),
)
def test_rename_deprecated_target_types_noops(lines: list[str]) -> None:
    result = maybe_rename_deprecated_targets(
        RenameDeprecatedTargetsRequest("BUILD", tuple(lines), colors_enabled=False),
        RenamedTargetTypes({"deprecated_name": "new_name"}),
    )
    assert not result.change_descriptions
    assert result.lines == tuple(lines)


@pytest.mark.parametrize(
    "lines,expected",
    (
        (["deprecated_name()"], ["new_name()"]),
        (["deprecated_name ( ) "], ["new_name ( ) "]),
        (["deprecated_name()  # comment"], ["new_name()  # comment"]),
        (["deprecated_name(", "", ")"], ["new_name(", "", ")"]),
    ),
)
def test_rename_deprecated_target_types_rewrite(lines: list[str], expected: list[str]) -> None:
    result = maybe_rename_deprecated_targets(
        RenameDeprecatedTargetsRequest("BUILD", tuple(lines), colors_enabled=False),
        RenamedTargetTypes({"deprecated_name": "new_name"}),
    )
    assert result.change_descriptions
    assert result.lines == tuple(expected)


# ------------------------------------------------------------------------------------------
# Renamed field types fixer
# ------------------------------------------------------------------------------------------


def test_determine_renamed_fields() -> None:
    class DeprecatedField(StringField):
        alias = "new_name"
        deprecated_alias = "old_name"
        deprecated_alias_removal_version = "99.9.0.dev0"

    class OkayField(StringField):
        alias = "okay"

    class Tgt(Target):
        alias = "tgt"
        core_fields = (DeprecatedField, OkayField)
        deprecated_alias = "deprecated_tgt"
        deprecated_alias_removal_version = "99.9.0.dev0"

    class TgtGenerator(TargetGenerator):
        alias = "generator"
        core_fields = ()
        moved_fields = (DeprecatedField, OkayField)

    registered_targets = RegisteredTargetTypes.create([Tgt, TgtGenerator])
    result = determine_renamed_field_types(registered_targets, UnionMembership({}))
    deprecated_fields = FrozenDict({DeprecatedField.deprecated_alias: DeprecatedField.alias})
    assert result.target_field_renames == FrozenDict(
        {k: deprecated_fields for k in (TgtGenerator.alias, Tgt.alias, Tgt.deprecated_alias)}
    )


@pytest.mark.parametrize(
    "lines",
    (
        # Already valid.
        ["target(new_name='')"],
        ["target(new_name = 56 ) "],
        ["target(foo=1, new_name=2)"],
        ["target(", "new_name", "=3)"],
        # Unrelated lines.
        ["", "123", "target()", "name='new_name'"],
        ["unaffected(deprecated_name='not this target')"],
        ["target(nested=here(deprecated_name='too deep'))"],
    ),
)
def test_rename_deprecated_field_types_noops(lines: list[str]) -> None:
    result = maybe_rename_deprecated_fields(
        RenameDeprecatedFieldsRequest("BUILD", tuple(lines), colors_enabled=False),
        RenamedFieldTypes.from_dict({"target": {"deprecated_name": "new_name"}}),
    )
    assert not result.change_descriptions
    assert result.lines == tuple(lines)


@pytest.mark.parametrize(
    "lines,expected",
    (
        (["tgt1(deprecated_name='')"], ["tgt1(new_name='')"]),
        (["tgt1 ( deprecated_name = ' ', ", ")"], ["tgt1 ( new_name = ' ', ", ")"]),
        (["tgt1(deprecated_name='')  # comment"], ["tgt1(new_name='')  # comment"]),
        (["tgt1(", "deprecated_name", "=", ")"], ["tgt1(", "new_name", "=", ")"]),
    ),
)
def test_rename_deprecated_field_types_rewrite(lines: list[str], expected: list[str]) -> None:
    result = maybe_rename_deprecated_fields(
        RenameDeprecatedFieldsRequest("BUILD", tuple(lines), colors_enabled=False),
        RenamedFieldTypes.from_dict({"tgt1": {"deprecated_name": "new_name"}}),
    )
    assert result.change_descriptions
    assert result.lines == tuple(expected)
