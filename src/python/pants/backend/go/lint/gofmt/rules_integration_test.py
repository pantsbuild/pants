# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.lint.gofmt.rules import GofmtFieldSet, GofmtRequest
from pants.backend.go.lint.gofmt.rules import rules as gofmt_rules
from pants.backend.go.lint.gofmt.subsystem import SUPPORTED_GOFMT_ARGS_AS_HELP
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
from pants.engine.internals.scheduler import ExecutionError
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
            QueryRule(FmtResult, (GofmtRequest.Batch,)),
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

BAD_FILE_TO_SIMPLIFY = dedent(
    """\
    package grok

    import (
    \t"fmt"
    )

    func Grok(s string) {
    \tfmt.Println(s[1:len(s)])
    }
    """
)

FIXED_BAD_FILE_TO_SIMPLIFY = dedent(
    """\
    package grok

    import (
    \t"fmt"
    )

    func Grok(s string) {
    \tfmt.Println(s[1:])
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
            GofmtRequest.Batch(
                "",
                input_sources.snapshot.files,
                partition_metadata=None,
                snapshot=input_sources.snapshot,
            ),
        ],
    )
    return fmt_result


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"f.go": GOOD_FILE, "go.mod": GO_MOD, "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')"}
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    fmt_result = run_gofmt(rule_runner, [tgt])
    assert fmt_result.stdout == ""
    assert fmt_result.output == rule_runner.make_snapshot({"f.go": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing_gofmt_flags(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "f.go": BAD_FILE_TO_SIMPLIFY,
            "go.mod": GO_MOD,
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    with pytest.raises(ExecutionError, match=SUPPORTED_GOFMT_ARGS_AS_HELP):
        run_gofmt(rule_runner, [tgt], extra_args=["--gofmt-args=-unsupported"])

    fmt_result = run_gofmt(
        rule_runner, [tgt], extra_args=["--gofmt-args=-s"]
    )  # -s flag will simplify the code
    assert fmt_result.stderr == ""
    assert fmt_result.output == rule_runner.make_snapshot({"f.go": FIXED_BAD_FILE_TO_SIMPLIFY})
    assert fmt_result.did_change is True


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"f.go": BAD_FILE, "go.mod": GO_MOD, "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')"}
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    fmt_result = run_gofmt(rule_runner, [tgt])
    assert fmt_result.stderr == ""
    assert fmt_result.output == rule_runner.make_snapshot({"f.go": FIXED_BAD_FILE})
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
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.go": GOOD_FILE, "bad.go": FIXED_BAD_FILE}
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
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good/f.go": GOOD_FILE, "bad/f.go": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True
