# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadata
from pants.backend.python.util_rules.pex_requirements import (
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
)
from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE, NO_TOOL_LOCKFILE
from pants.core.goals.update_build_files import (
    FormatWithBlackRequest,
    FormatWithYapfRequest,
    RewrittenBuildFile,
    RewrittenBuildFileRequest,
    UpdateBuildFilesGoal,
    UpdateBuildFilesSubsystem,
    format_build_file_with_black,
    format_build_file_with_yapf,
    update_build_files,
)
from pants.core.target_types import GenericTarget
from pants.core.util_rules import config_files
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.rules import SubsystemRule, rule
from pants.engine.unions import UnionRule
from pants.option.ranked_value import Rank, RankedValue
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import GoalRuleResult, MockGet, RuleRunner, run_rule_with_mocks

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
        request.path, (*request.lines, "# added line"), change_descriptions=("Add a new line",)
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
    generic_goal_rule_runner.write_files({"BUILD": "# line\n", "dir/BUILD": "# line 1\n# line 2\n"})
    result = generic_goal_rule_runner.run_goal_rule(UpdateBuildFilesGoal, args=["::"])
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
    assert (
        Path(generic_goal_rule_runner.build_root, "BUILD").read_text() == "# added line\n# line\n"
    )
    assert (
        Path(generic_goal_rule_runner.build_root, "dir/BUILD").read_text()
        == "# added line\n# line 2\n# line 1\n"
    )


def test_goal_check_mode(generic_goal_rule_runner: RuleRunner) -> None:
    """Checks that we correctly set the exit code and pipe fixers to each other."""
    generic_goal_rule_runner.write_files({"BUILD": "# line\n", "dir/BUILD": "# line 1\n# line 2\n"})
    result = generic_goal_rule_runner.run_goal_rule(
        UpdateBuildFilesGoal,
        global_args=["--pants-bin-name=./custom_pants"],
        args=["--check", "::"],
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
    assert Path(generic_goal_rule_runner.build_root, "BUILD").read_text() == "# line\n"
    assert (
        Path(generic_goal_rule_runner.build_root, "dir/BUILD").read_text() == "# line 1\n# line 2\n"
    )


def test_find_python_interpreter_constraints_from_lockfile() -> None:
    default_metadata = PythonLockfileMetadata.new(
        valid_for_interpreter_constraints=InterpreterConstraints(["==2.7.*"]),
        requirements=set(),
        requirement_constraints=set(),
        only_binary=set(),
        no_binary=set(),
        manylinux=None,
    )

    def assert_ics(
        lckfile: str,
        expected: list[str],
        *,
        ics: RankedValue = RankedValue(Rank.HARDCODED, Black.default_interpreter_constraints),
        metadata: PythonLockfileMetadata | None = default_metadata,
    ) -> None:
        black = create_subsystem(
            Black,
            lockfile=lckfile,
            interpreter_constraints=ics,
            version="v",
            install_from_resolve=None,
            extra_requirements=[],
        )
        loaded_lock = LoadedLockfile(
            EMPTY_DIGEST,
            "black.lock",
            metadata=metadata,
            requirement_estimate=1,
            is_pex_native=True,
            as_constraints_strings=None,
            original_lockfile=Lockfile(
                "black.lock", url_description_of_origin="foo", resolve_name="black"
            ),
        )
        result = run_rule_with_mocks(
            Black._find_python_interpreter_constraints_from_lockfile,
            rule_args=[black],
            mock_gets=[
                MockGet(
                    output_type=LoadedLockfile,
                    input_types=(LoadedLockfileRequest,),
                    mock=lambda _: loaded_lock,
                )
            ],
        )
        assert result == InterpreterConstraints(expected)

    # If ICs are set by user, always use those.
    for lockfile in (NO_TOOL_LOCKFILE, DEFAULT_TOOL_LOCKFILE, "black.lock"):
        assert_ics(lockfile, ["==3.8.*"], ics=RankedValue(Rank.CONFIG, ["==3.8.*"]))

    assert_ics(NO_TOOL_LOCKFILE, Black.default_interpreter_constraints)
    assert_ics(DEFAULT_TOOL_LOCKFILE, Black.default_interpreter_constraints)

    assert_ics("black.lock", ["==2.7.*"])
    assert_ics("black.lock", Black.default_interpreter_constraints, metadata=None)


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
        ),
        target_types=[GenericTarget],
    )


def test_black_fixer_fixes(black_rule_runner: RuleRunner) -> None:
    black_rule_runner.write_files({"BUILD": "target( name =  't' )"})
    result = black_rule_runner.run_goal_rule(
        UpdateBuildFilesGoal, args=["::"], env_inherit=BLACK_ENV_INHERIT
    )
    assert result.exit_code == 0
    assert result.stdout == dedent(
        """\
        Updated BUILD:
          - Format with Black
        """
    )
    assert Path(black_rule_runner.build_root, "BUILD").read_text() == 'target(name="t")\n'


def test_black_fixer_noops(black_rule_runner: RuleRunner) -> None:
    black_rule_runner.write_files({"BUILD": 'target(name="t")\n'})
    result = black_rule_runner.run_goal_rule(
        UpdateBuildFilesGoal, args=["::"], env_inherit=BLACK_ENV_INHERIT
    )
    assert result.exit_code == 0
    assert Path(black_rule_runner.build_root, "BUILD").read_text() == 'target(name="t")\n'


def test_black_fixer_args(black_rule_runner: RuleRunner) -> None:
    black_rule_runner.write_files({"BUILD": "target(name='t')\n"})
    result = black_rule_runner.run_goal_rule(
        UpdateBuildFilesGoal,
        global_args=["--black-args='--skip-string-normalization'"],
        args=["::"],
        env_inherit=BLACK_ENV_INHERIT,
    )
    assert result.exit_code == 0
    assert Path(black_rule_runner.build_root, "BUILD").read_text() == "target(name='t')\n"


def test_black_config(black_rule_runner: RuleRunner) -> None:
    black_rule_runner.write_files(
        {
            "pyproject.toml": "[tool.black]\nskip-string-normalization = 'true'\n",
            "BUILD": "target(name='t')\n",
        },
    )
    result = black_rule_runner.run_goal_rule(
        UpdateBuildFilesGoal, args=["::"], env_inherit=BLACK_ENV_INHERIT
    )
    assert result.exit_code == 0
    assert Path(black_rule_runner.build_root, "BUILD").read_text() == "target(name='t')\n"


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
        ),
        target_types=[GenericTarget],
    )
    rule_runner.write_files({"BUILD": build_content})
    goal_result = rule_runner.run_goal_rule(
        UpdateBuildFilesGoal,
        args=["--update-build-files-formatter=yapf", "::"],
        global_args=extra_args or (),
        env_inherit=BLACK_ENV_INHERIT,
    )
    rewritten_build = Path(rule_runner.build_root, "BUILD").read_text()
    return goal_result, rewritten_build


def test_yapf_fixer_fixes() -> None:
    result, build = run_yapf("target( name =  't' )")
    assert result.exit_code == 0
    assert result.stdout == dedent(
        """\
        Updated BUILD:
          - Format with Yapf
        """
    )
    assert build == "target(name='t')\n"


def test_yapf_fixer_noops() -> None:
    result, build = run_yapf('target(name="t")\n')
    assert result.exit_code == 0
    assert not result.stdout
    assert build == 'target(name="t")\n'
