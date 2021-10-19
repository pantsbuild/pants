# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.lint import fmt
from pants.backend.go.lint.vet import skip_field
from pants.backend.go.lint.vet.rules import GoVetFieldSet, GoVetRequest
from pants.backend.go.lint.vet.rules import rules as go_vet_rules
from pants.backend.go.lint.vet.subsystem import GoVetSubsystem
from pants.backend.go.target_types import GoFirstPartyPackageTarget, GoModTarget
from pants.backend.go.util_rules import (
    first_party_pkg,
    go_mod,
    import_analysis,
    sdk,
    third_party_pkg,
)
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import source_files
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.rules import SubsystemRule
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture()
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[GoModTarget, GoFirstPartyPackageTarget],
        rules=[
            *fmt.rules(),
            *skip_field.rules(),
            *go_vet_rules(),
            *source_files.rules(),
            *target_type_rules.rules(),
            *first_party_pkg.rules(),
            *third_party_pkg.rules(),
            *sdk.rules(),
            *go_mod.rules(),
            *import_analysis.rules(),
            QueryRule(LintResults, (GoVetRequest,)),
            SubsystemRule(GoVetSubsystem),
        ],
    )
    rule_runner.set_options(
        ["--backend-packages=pants.backend.experimental.go.lint.vet"], env_inherit={"PATH"}
    )
    return rule_runner


GOOD_FILE = dedent(
    """\
    package grok
    import "fmt"
    func good() {
        s := "Hello World"
        fmt.Printf("%s", s)
    }
    """
)

BAD_FILE = dedent(
    """\
    package grok
    import "fmt"
    func bad() {
        fmt.Printf("%s")
    }
    """
)

GO_MOD = dedent(
    """\
    module example.com/fmt
    go 1.17
    """
)


def run_go_vet(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> tuple[LintResult, ...]:
    args = (extra_args or []) + ["--backend-packages=pants.backend.experimental.go.lint.vet"]
    rule_runner.set_options(
        args,
        env_inherit={"PATH"},
    )
    field_sets = [GoVetFieldSet.create(tgt) for tgt in targets]
    lint_results = rule_runner.request(LintResults, [GoVetRequest(field_sets)])
    return lint_results.results


def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.go": GOOD_FILE, "go.mod": GO_MOD, "BUILD": "go_mod(name='mod')"})
    tgt = rule_runner.get_target(Address("", target_name="mod", generated_name="./"))
    lint_results = run_go_vet(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.go": BAD_FILE, "go.mod": GO_MOD, "BUILD": "go_mod(name='mod')"})
    tgt = rule_runner.get_target(Address("", target_name="mod", generated_name="./"))
    lint_results = run_go_vet(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "f.go" in lint_results[0].stdout


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')",
            "good/f.go": GOOD_FILE,
            "bad/f.go": BAD_FILE,
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="mod", generated_name="./good")),
        rule_runner.get_target(Address("", target_name="mod", generated_name="./bad")),
    ]
    lint_results = run_go_vet(rule_runner, tgts)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad/f.go" in lint_results[0].stdout
    assert "good/f.go" not in lint_results[0].stdout


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.go": BAD_FILE, "go.mod": GO_MOD, "BUILD": "go_mod(name='mod')"})
    tgt = rule_runner.get_target(Address("", target_name="mod", generated_name="./"))
    lint_results = run_go_vet(rule_runner, [tgt], extra_args=["--go-vet-skip"])
    assert not lint_results
