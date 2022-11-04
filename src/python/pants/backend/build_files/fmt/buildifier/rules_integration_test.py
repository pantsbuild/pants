# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.build_files.fmt.buildifier.rules import BuildifierRequest
from pants.backend.build_files.fmt.buildifier.rules import rules as buildifier_rules
from pants.backend.codegen.protobuf.target_types import rules as target_types_rules
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import external_tool
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import Snapshot
from pants.testutil.rule_runner import QueryRule, RuleRunner


class Materials:
    def __init__(self, **kwargs):
        pass


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *buildifier_rules(),
            *external_tool.rules(),
            *target_types_rules(),
            QueryRule(FmtResult, [BuildifierRequest.Batch]),
        ],
        # NB: Objects are easier to test with
        objects={"materials": Materials},
    )


GOOD_FILE = dedent(
    """\
    materials(
        drywall = 40,
        status = "paid",
        studs = 200,
    )
    """
)

BAD_FILE = dedent(
    """\
    materials(status='paid', studs=200, drywall=40)
    """
)


def run_buildifier(rule_runner: RuleRunner) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.build_files.fmt.buildifier"],
        env_inherit={"PATH", "PYENV_ROOT"},
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**/BUILD"])])
    fmt_result = rule_runner.request(
        FmtResult,
        [
            BuildifierRequest.Batch("", snapshot.files, partition_metadata=None, snapshot=snapshot),
        ],
    )
    return fmt_result


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": GOOD_FILE})
    fmt_result = run_buildifier(rule_runner)
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": BAD_FILE})
    fmt_result = run_buildifier(rule_runner)
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": GOOD_FILE})
    assert fmt_result.did_change is True


def test_multiple_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"good/BUILD": GOOD_FILE, "bad/BUILD": BAD_FILE})
    fmt_result = run_buildifier(rule_runner)
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good/BUILD": GOOD_FILE, "bad/BUILD": GOOD_FILE}
    )
    assert fmt_result.did_change is True
