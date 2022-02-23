# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

import pytest

from pants.core.goals.check import CheckResult, CheckResults
from pants.core.goals.style_request import (
    StyleRequest,
    determine_specified_tool_names,
    write_reports,
)
from pants.core.util_rules.distdir import DistDir
from pants.engine.fs import EMPTY_DIGEST, Workspace
from pants.testutil.rule_runner import RuleRunner


def test_determine_specified_tool_names() -> None:
    class StyleReq(StyleRequest):
        name = "my-tool"

    with pytest.raises(ValueError) as exc:
        determine_specified_tool_names(
            "fake-goal",
            only_option=["bad"],
            all_style_requests=[StyleReq],
            extra_valid_names=["extra-tool"],
        )
    assert (
        "Unrecognized name with the option `--fake-goal-only`: 'bad'\n\n"
        "All valid names: ['extra-tool', 'my-tool']"
    ) in str(exc.value)


def test_write_reports() -> None:
    rule_runner = RuleRunner()
    report_digest = rule_runner.make_snapshot_of_empty_files(["r.txt"]).digest
    no_results = CheckResults([], checker_name="none")
    _empty_result = CheckResult(0, "", "", report=EMPTY_DIGEST)
    empty_results = CheckResults([_empty_result], checker_name="empty")
    _single_result = CheckResult(0, "", "", report=report_digest)
    single_results = CheckResults([_single_result], checker_name="single")
    duplicate_results = CheckResults(
        [_single_result, _single_result, _empty_result], checker_name="duplicate"
    )
    partition_results = CheckResults(
        [
            CheckResult(0, "", "", report=report_digest, partition_description="p1"),
            CheckResult(0, "", "", report=report_digest, partition_description="p2"),
        ],
        checker_name="partition",
    )
    partition_duplicate_results = CheckResults(
        [
            CheckResult(0, "", "", report=report_digest, partition_description="p"),
            CheckResult(0, "", "", report=report_digest, partition_description="p"),
        ],
        checker_name="partition_duplicate",
    )

    def get_name(res: CheckResults) -> str:
        return res.checker_name

    write_reports(
        (
            no_results,
            empty_results,
            single_results,
            duplicate_results,
            partition_results,
            partition_duplicate_results,
        ),
        Workspace(rule_runner.scheduler, _enforce_effects=False),
        DistDir(Path("dist")),
        goal_name="check",
        get_name=get_name,
    )

    check_dir = Path(rule_runner.build_root, "dist", "check")
    assert (check_dir / "none").exists() is False
    assert (check_dir / "empty").exists() is False
    assert (check_dir / "single/r.txt").exists() is True

    assert (check_dir / "duplicate/all/r.txt").exists() is True
    assert (check_dir / "duplicate/all_/r.txt").exists() is True

    assert (check_dir / "partition/p1/r.txt").exists() is True
    assert (check_dir / "partition/p2/r.txt").exists() is True

    assert (check_dir / "partition_duplicate/p/r.txt").exists() is True
    assert (check_dir / "partition_duplicate/p_/r.txt").exists() is True
