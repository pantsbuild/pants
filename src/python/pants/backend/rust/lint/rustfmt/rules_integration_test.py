# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.rust.lint.rustfmt.rules import RustfmtFieldSet, RustfmtRequest
from pants.backend.rust.lint.rustfmt.rules import rules as rustfmt_rules
from pants.backend.rust.target_types import RustPackageTarget
from pants.backend.rust.util_rules import toolchains
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import source_files, system_binaries
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture()
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[RustPackageTarget],
        rules=[
            *rustfmt_rules(),
            *toolchains.rules(),
            *source_files.rules(),
            *system_binaries.rules(),
            QueryRule(FmtResult, (RustfmtRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


GOOD_FILE = dedent(
    """\
    use Foo::Bar;
    fn grok(s: &str) {}
    """
)

BAD_FILE = dedent(
    """\
    use  Foo::Bar;
    fn grok(s: &str) {
    println!("Hello World {}!", s);
    }
    """
)

FIXED_BAD_FILE = dedent(
    """\
    use Foo::Bar;
    fn grok(s: &str) {
        println!("Hello World {}!", s);
    }
    """
)


def run_rustfmt(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> FmtResult:
    rule_runner.set_options(extra_args or (), env_inherit={"PATH"})
    field_sets = [RustfmtFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            RustfmtRequest.Batch(
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
        {"src/lib.rs": GOOD_FILE, "Cargo.toml": "", "BUILD": "rust_package(name='package')"}
    )
    tgt = rule_runner.get_target(Address("", target_name="package"))
    fmt_result = run_rustfmt(rule_runner, [tgt])

    assert fmt_result.stdout.strip() == ""
    assert fmt_result.output == rule_runner.make_snapshot({"src/lib.rs": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"src/lib.rs": BAD_FILE, "Cargo.toml": "", "BUILD": "rust_package(name='package')"}
    )
    tgt = rule_runner.get_target(Address("", target_name="package"))
    fmt_result = run_rustfmt(rule_runner, [tgt])
    assert fmt_result.stderr == ""
    assert fmt_result.output == rule_runner.make_snapshot({"src/lib.rs": FIXED_BAD_FILE})
    assert fmt_result.did_change is True


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/good.rs": GOOD_FILE,
            "src/bad.rs": BAD_FILE,
            "Cargo.toml": "",
            "BUILD": "rust_package(name='package')",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="package"))
    fmt_result = run_rustfmt(rule_runner, [tgt])
    assert fmt_result.output == rule_runner.make_snapshot(
        {"src/good.rs": GOOD_FILE, "src/bad.rs": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good/src/f.rs": GOOD_FILE,
            "good/Cargo.toml": "",
            "good/BUILD": "rust_package()",
            "bad/src/f.rs": BAD_FILE,
            "bad/Cargo.toml": "",
            "bad/BUILD": "rust_package()",
        }
    )
    tgts = [rule_runner.get_target(Address("good")), rule_runner.get_target(Address("bad"))]
    fmt_result = run_rustfmt(rule_runner, tgts)
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good/src/f.rs": GOOD_FILE, "bad/src/f.rs": FIXED_BAD_FILE},
    )
    assert fmt_result.did_change is True
