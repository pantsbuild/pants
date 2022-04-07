# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.lint.gofmt.rules import GofmtFieldSet, GofmtRequest
from pants.backend.go.lint.gofmt.rules import rules as gofmt_rules
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    first_party_pkg,
    go_mod,
    link,
    sdk,
    third_party_pkg,
)
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.native_engine import Snapshot
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture()
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[GoModTarget, GoPackageTarget],
        rules=[
            *gofmt_rules(),
            *source_files.rules(),
            *target_type_rules.rules(),
            *first_party_pkg.rules(),
            *third_party_pkg.rules(),
            *sdk.rules(),
            *go_mod.rules(),
            *build_pkg.rules(),
            *link.rules(),
            *assembly.rules(),
            QueryRule(FmtResult, (GofmtRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


GOOD_FILE = dedent(
    """\
    package grok

    import (
    \t"fmt"
    )

    func Grok(s string) {
    \tfmt.Println(s)
    }
    """
)

BAD_FILE = dedent(
    """\
    package grok
    import (
    "fmt"
    )

    func Grok(s string) {
    fmt.Println(s)
    }
    """
)

FIXED_BAD_FILE = dedent(
    """\
    package grok

    import (
    \t"fmt"
    )

    func Grok(s string) {
    \tfmt.Println(s)
    }
    """
)


GO_MOD = dedent(
    """\
    module example.com/fmt
    go 1.17
    """
)


def run_gofmt(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> FmtResult:
    rule_runner.set_options(extra_args or (), env_inherit={"PATH"})
    field_sets = [GofmtFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            GofmtRequest(field_sets, snapshot=input_sources.snapshot),
        ],
    )
    return fmt_result


def get_snapshot(rule_runner: RuleRunner, source_files: dict[str, str]) -> Snapshot:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    digest = rule_runner.request(Digest, [CreateDigest(files)])
    return rule_runner.request(Snapshot, [digest])


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"f.go": GOOD_FILE, "go.mod": GO_MOD, "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')"}
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    fmt_result = run_gofmt(rule_runner, [tgt])
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_snapshot(rule_runner, {"f.go": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"f.go": BAD_FILE, "go.mod": GO_MOD, "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')"}
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    fmt_result = run_gofmt(rule_runner, [tgt])
    assert fmt_result.stderr == ""
    assert fmt_result.output == get_snapshot(rule_runner, {"f.go": FIXED_BAD_FILE})
    assert fmt_result.did_change is True


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.go": GOOD_FILE,
            "bad.go": BAD_FILE,
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    fmt_result = run_gofmt(rule_runner, [tgt])
    assert fmt_result.output == get_snapshot(
        rule_runner, {"good.go": GOOD_FILE, "bad.go": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')",
            "good/f.go": GOOD_FILE,
            "good/BUILD": "go_package()",
            "bad/f.go": BAD_FILE,
            "bad/BUILD": "go_package()",
        }
    )
    tgts = [rule_runner.get_target(Address("good")), rule_runner.get_target(Address("bad"))]
    fmt_result = run_gofmt(rule_runner, tgts)
    assert fmt_result.output == get_snapshot(
        rule_runner, {"good/f.go": GOOD_FILE, "bad/f.go": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"f.go": BAD_FILE, "go.mod": GO_MOD, "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')"}
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    fmt_result = run_gofmt(rule_runner, [tgt], extra_args=["--gofmt-skip"])
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False
