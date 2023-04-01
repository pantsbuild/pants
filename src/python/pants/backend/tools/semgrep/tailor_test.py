# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.tools.semgrep import tailor
from pants.backend.tools.semgrep.tailor import PutativeSemgrepTargetsRequest
from pants.backend.tools.semgrep.target_types import SemgrepRuleSourcesGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        ((), {}),
        (("foo/bar/.semgrep.yml",), {"foo/bar": {".semgrep.yml"}}),
        (("foo/bar/.semgrep/baz.yml",), {"foo/bar": {".semgrep/baz.yml"}}),
        (
            (
                "foo/bar/.semgrep.yml",
                "foo/bar/.semgrep/baz.yml",
            ),
            {"foo/bar": {".semgrep.yml", ".semgrep/baz.yml"}},
        ),
        (
            (
                "foo/.semgrep/baz.yml",
                "foo/bar/.semgrep.yml",
                "foo/bar/qux/.semgrep.yml",
            ),
            {
                "foo": {".semgrep/baz.yml"},
                "foo/bar": {".semgrep.yml"},
                "foo/bar/qux": {".semgrep.yml"},
            },
        ),
        # at the top level should be okay too
        ((".semgrep.yml", ".semgrep/foo.yml"), {"": {".semgrep.yml", ".semgrep/foo.yml"}}),
    ],
)
def test_group_by_semgrep_dir(paths: tuple[str, ...], expected: dict[str, set[str]]):
    assert tailor._group_by_semgrep_dir(paths) == expected


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativeSemgrepTargetsRequest, AllOwnedSources)),
        ],
        target_types=[SemgrepRuleSourcesGeneratorTarget],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/owned/.semgrep.yml": "rules: []",
            "src/owned/sub/.semgrep/foo.yaml": "rules: []",
            "src/unowned/.semgrep.yaml": "rules: []",
            "src/unowned/sub/.semgrep/foo.yml": "rules: []",
            "src/unowned/sub/.semgrep/bar.yaml": "rules: []",
            "src/unowned/sub/.semgrep.yml": "rules: []",
            # other YAML files aren't always Semgrep
            "src/unowned/not_obviously_semgrep.yaml": "rules: []",
        }
    )

    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeSemgrepTargetsRequest(("src/owned", "src/unowned", "src/unowned/sub")),
            AllOwnedSources(["src/owned/.semgrep.yml", "src/owned/sub/.semgrep/foo.yaml"]),
        ],
    )

    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                SemgrepRuleSourcesGeneratorTarget,
                "src/unowned",
                "semgrep",
                [".semgrep.yaml"],
            ),
            PutativeTarget.for_target_type(
                SemgrepRuleSourcesGeneratorTarget,
                "src/unowned/sub",
                "semgrep",
                [".semgrep.yml", ".semgrep/bar.yaml", ".semgrep/foo.yml"],
            ),
        ],
    )


def test_find_putative_targets_when_disabled(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/unowned/.semgrep.yml": "{}",
        }
    )

    rule_runner.set_options(["--no-semgrep-tailor-rule-targets"])

    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeSemgrepTargetsRequest(("src/unowned",)),
            AllOwnedSources(),
        ],
    )
    assert putative_targets == PutativeTargets()
