# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap
from typing import List, Sequence, Tuple

import pytest

from pants.backend.go.lint import fmt
from pants.backend.go.lint.gofmt.rules import GofmtFieldSet, GofmtRequest
from pants.backend.go.lint.gofmt.rules import rules as gofmt_rules
from pants.backend.go.target_types import GoBinary, GoPackage
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import external_tool, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture()
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[GoBinary, GoPackage],
        rules=[
            *external_tool.rules(),
            *fmt.rules(),
            *gofmt_rules(),
            *source_files.rules(),
            QueryRule(LintResults, (GofmtRequest,)),
            QueryRule(FmtResult, (GofmtRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
    )


GOOD_SOURCE = FileContent(
    "good.go",
    textwrap.dedent(
        """\
    package grok

    import (
    \t"fmt"
    )

    func Grok(s string) {
    \tfmt.Println(s)
    }
    """
    ).encode("utf-8"),
)

BAD_SOURCE = FileContent(
    "bad.go",
    textwrap.dedent(
        """\
    package grok
    import (
    "fmt"
    )

    func Grok(s string) {
    fmt.Println(s)
    }
    """
    ).encode("utf-8"),
)

FIXED_BAD_SOURCE = FileContent(
    "bad.go",
    textwrap.dedent(
        """\
    package grok

    import (
    \t"fmt"
    )

    func Grok(s string) {
    \tfmt.Println(s)
    }
    """
    ).encode("utf-8"),
)


def make_target(
    rule_runner: RuleRunner, source_files: List[FileContent], *, target_name="target"
) -> Target:
    for source_file in source_files:
        rule_runner.create_file(f"{source_file.path}", source_file.content.decode())
    rule_runner.add_to_build_file(
        "",
        f"go_package(name='{target_name}')\n",
    )
    return rule_runner.get_target(Address("", target_name=target_name))


def run_gofmt(
    rule_runner: RuleRunner,
    targets: List[Target],
    *,
    skip: bool = False,
) -> Tuple[Sequence[LintResult], FmtResult]:
    args = ["--backend-packages=pants.backend.go"]
    if skip:
        args.append("--gofmt-skip")
    rule_runner.set_options(args)
    field_sets = [GofmtFieldSet.create(tgt) for tgt in targets]
    lint_results = rule_runner.request(LintResults, [GofmtRequest(field_sets)])
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            GofmtRequest(field_sets, prior_formatter_result=input_sources.snapshot),
        ],
    )
    return lint_results.results, fmt_result


def get_digest(rule_runner: RuleRunner, source_files: List[FileContent]) -> Digest:
    return rule_runner.request(Digest, [CreateDigest(source_files)])


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    lint_results, fmt_result = run_gofmt(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE])
    assert fmt_result.did_change is False


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results, fmt_result = run_gofmt(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.go" in lint_results[0].stdout
    assert fmt_result.stderr == ""
    assert fmt_result.output == get_digest(rule_runner, [FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    lint_results, fmt_result = run_gofmt(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.go" in lint_results[0].stdout
    assert "good.go" not in lint_results[0].stdout
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    targets = [
        make_target(rule_runner, [GOOD_SOURCE], target_name="tgt_good"),
        make_target(rule_runner, [BAD_SOURCE], target_name="tgt_bad"),
    ]
    lint_results, fmt_result = run_gofmt(rule_runner, targets)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.go" in lint_results[0].stdout
    assert "good.go" not in lint_results[0].stdout
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results, fmt_result = run_gofmt(rule_runner, [target], skip=True)
    assert not lint_results
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False
