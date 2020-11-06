# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

import pytest

from pants.backend.codegen.write_codegen_goal import WriteCodegen
from pants.backend.codegen.write_codegen_goal import rules as write_codegen_rules
from pants.core.target_types import FilesSources, ResourcesSources
from pants.core.util_rules import distdir
from pants.engine.fs import CreateDigest, FileContent, Snapshot
from pants.engine.rules import Get, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest, Sources, Target
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner


class Gen1Sources(Sources):
    pass


class Gen2Sources(Sources):
    pass


class Gen1Target(Target):
    alias = "gen1"
    core_fields = (Gen1Sources,)


class Gen2Target(Target):
    alias = "gen2"
    core_fields = (Gen2Sources,)


class Gen1Request(GenerateSourcesRequest):
    input = Gen1Sources
    output = FilesSources


class Gen2Request(GenerateSourcesRequest):
    input = Gen2Sources
    output = ResourcesSources


@rule
async def gen1(_: Gen1Request) -> GeneratedSources:
    result = await Get(Snapshot, CreateDigest([FileContent("assets/README.md", b"Hello!")]))
    return GeneratedSources(result)


@rule
async def gen2(_: Gen2Request) -> GeneratedSources:
    result = await Get(Snapshot, CreateDigest([FileContent("src/haskell/app.hs", b"10 * 4")]))
    return GeneratedSources(result)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *write_codegen_rules(),
            gen1,
            gen2,
            UnionRule(GenerateSourcesRequest, Gen1Request),
            UnionRule(GenerateSourcesRequest, Gen2Request),
            *distdir.rules(),
        ],
        target_types=[Gen1Target, Gen2Target],
    )


def test_no_codegen_targets(rule_runner: RuleRunner, caplog) -> None:
    result = rule_runner.run_goal_rule(WriteCodegen)
    assert result.exit_code == 0
    assert len(caplog.records) == 1
    assert "No codegen files/targets matched. All codegen target types: gen1, gen2" in caplog.text


def test_write_codegen(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file("", "gen1(name='gen1')\ngen2(name='gen2')\n")
    result = rule_runner.run_goal_rule(WriteCodegen, args=["::"])
    assert result.exit_code == 0
    parent_dir = Path(rule_runner.build_root, "dist", "codegen")
    assert (parent_dir / "assets" / "README.md").read_text() == "Hello!"
    assert (parent_dir / "src" / "haskell" / "app.hs").read_text() == "10 * 4"
