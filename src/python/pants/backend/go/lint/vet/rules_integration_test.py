# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.lint.vet import skip_field
from pants.backend.go.lint.vet.rules import GoVetFieldSet, GoVetRequest
from pants.backend.go.lint.vet.rules import rules as go_vet_rules
from pants.backend.go.lint.vet.subsystem import GoVetSubsystem
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    first_party_pkg,
    go_mod,
    import_analysis,
    link,
    sdk,
    third_party_pkg,
)
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import source_files
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.fs import rules as fs_rules
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture()
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[GoModTarget, GoPackageTarget],
        rules=[
            *skip_field.rules(),
            *go_vet_rules(),
            *source_files.rules(),
            *target_type_rules.rules(),
            *first_party_pkg.rules(),
            *third_party_pkg.rules(),
            *sdk.rules(),
            *go_mod.rules(),
            *import_analysis.rules(),
            *link.rules(),
            *build_pkg.rules(),
            *assembly.rules(),
            *fs_rules(),
            *archive_rules(),
            QueryRule(Partitions, [GoVetRequest.PartitionRequest]),
            QueryRule(LintResult, [GoVetRequest.Batch]),
            *GoVetSubsystem.rules(),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
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
    args = extra_args or []
    rule_runner.set_options(args, env_inherit={"PATH"})
    partitions = rule_runner.request(
        Partitions,
        [GoVetRequest.PartitionRequest(tuple(GoVetFieldSet.create(tgt) for tgt in targets))],
    )
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [GoVetRequest.Batch("", partition.elements, partition.metadata)],
        )
        results.append(result)
    return tuple(results)


def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.go": GOOD_FILE,
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')\n",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    lint_results = run_go_vet(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""


def _check_err_msg(result_stderr: str) -> None:
    # Note: `go vet` sometimes emits "fmt.Printf" and sometimes just "Printf", depending on conditions
    # which are unclear so let the `fmt.` part be optional.
    assert re.search(
        r"./f.go:4:5: (fmt\.)?Printf format %s reads arg #1, but call has 0 args", result_stderr
    )


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.go": BAD_FILE,
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')\n",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    lint_results = run_go_vet(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code != 0
    _check_err_msg(lint_results[0].stderr)


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')\n",
            "good/BUILD": "go_package()\n",
            "good/f.go": GOOD_FILE,
            "bad/BUILD": "go_package()\n",
            "bad/f.go": BAD_FILE,
        }
    )
    tgts = [
        rule_runner.get_target(Address("good", target_name="good")),
        rule_runner.get_target(Address("bad", target_name="bad")),
    ]
    lint_results = run_go_vet(rule_runner, tgts)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code != 0
    _check_err_msg(lint_results[0].stderr)
    assert "good/f.go" not in lint_results[0].stdout


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.go": BAD_FILE,
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')\n",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    lint_results = run_go_vet(rule_runner, [tgt], extra_args=["--go-vet-skip"])
    assert not lint_results
