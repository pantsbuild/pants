# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from pants.core.goals.check import CheckResult, CheckResults
from pants.core.goals.multi_tool_goal_helper import determine_specified_tool_ids, write_reports
from pants.core.util_rules.distdir import DistDir
from pants.engine.fs import EMPTY_DIGEST, Workspace
from pants.testutil.rule_runner import RuleRunner
from pants.util.meta import classproperty
from pants.util.strutil import softwrap


def test_determine_specified_tool_ids() -> None:
    class StyleReq:
        @classproperty
        def tool_id(cls) -> str:
            return "my-tool"

    with pytest.raises(ValueError) as exc:
        determine_specified_tool_ids(
            "fake-goal",
            only_option=["bad"],
            all_requests=[StyleReq],
        )
    assert (
        softwrap(
            """
            Unrecognized name with the option `--fake-goal-only`: 'bad'

            All valid names: ['my-tool']
            """
        )
        in str(exc.value)
    )


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

    results_by_name: dict[str, list[CheckResult]] = defaultdict(list)
    for results in (
        no_results,
        empty_results,
        single_results,
        duplicate_results,
        partition_results,
        partition_duplicate_results,
    ):
        results_by_name[results.checker_name].extend(results.results)

    write_reports(
        results_by_name,
        Workspace(rule_runner.scheduler, _enforce_effects=False),
        DistDir(Path("dist")),
        goal_name="check",
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
