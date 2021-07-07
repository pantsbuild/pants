# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.core.goals.style_request import write_reports
from pants.core.goals.typecheck import TypecheckResult, TypecheckResults
from pants.core.util_rules.distdir import DistDir
from pants.engine.fs import EMPTY_DIGEST, Workspace
from pants.testutil.rule_runner import RuleRunner


def test_write_reports() -> None:
    rule_runner = RuleRunner()
    report_digest = rule_runner.make_snapshot_of_empty_files(["r.txt"]).digest
    no_results = TypecheckResults([], typechecker_name="none")
    _empty_result = TypecheckResult(0, "", "", report=EMPTY_DIGEST)
    empty_results = TypecheckResults([_empty_result], typechecker_name="empty")
    _single_result = TypecheckResult(0, "", "", report=report_digest)
    single_results = TypecheckResults([_single_result], typechecker_name="single")
    duplicate_results = TypecheckResults(
        [_single_result, _single_result, _empty_result], typechecker_name="duplicate"
    )
    partition_results = TypecheckResults(
        [
            TypecheckResult(0, "", "", report=report_digest, partition_description="p1"),
            TypecheckResult(0, "", "", report=report_digest, partition_description="p2"),
        ],
        typechecker_name="partition",
    )
    partition_duplicate_results = TypecheckResults(
        [
            TypecheckResult(0, "", "", report=report_digest, partition_description="p"),
            TypecheckResult(0, "", "", report=report_digest, partition_description="p"),
        ],
        typechecker_name="partition_duplicate",
    )

    def get_tool_name(res: TypecheckResults) -> str:
        return res.typechecker_name

    write_reports(
        (
            no_results,
            empty_results,
            single_results,
            duplicate_results,
            partition_results,
            partition_duplicate_results,
        ),
        Workspace(rule_runner.scheduler),
        DistDir(Path("dist")),
        goal_name="typecheck",
        get_tool_name=get_tool_name,
    )

    typecheck_dir = Path(rule_runner.build_root, "dist", "typecheck")
    assert (typecheck_dir / "none").exists() is False
    assert (typecheck_dir / "empty").exists() is False
    assert (typecheck_dir / "single/r.txt").exists() is True

    assert (typecheck_dir / "duplicate/all/r.txt").exists() is True
    assert (typecheck_dir / "duplicate/all_/r.txt").exists() is True

    assert (typecheck_dir / "partition/p1/r.txt").exists() is True
    assert (typecheck_dir / "partition/p2/r.txt").exists() is True

    assert (typecheck_dir / "partition_duplicate/p/r.txt").exists() is True
    assert (typecheck_dir / "partition_duplicate/p_/r.txt").exists() is True
