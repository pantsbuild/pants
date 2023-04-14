# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Sequence

import pytest

from pants.core.goals.lint import LintResult, Partitions
from pants.core.target_types import FileTarget
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import QueryRule, RuleRunner

from .dependency_inference import rules as dependency_inference_rules
from .rules import PartitionMetadata, SemgrepRequest
from .rules import rules as semgrep_rules
from .subsystem import Semgrep, SemgrepFieldSet
from .subsystem import rules as semgrep_subsystem_rules
from .target_types import SemgrepRuleSource, SemgrepRuleSourcesGeneratorTarget

DIR = "src"

GOOD_FILE = "good_pattern"
BAD_FILE = "bad_pattern"
RULES = dedent(
    """\
    rules:
    - id: find-bad-pattern
      patterns:
        - pattern: bad_pattern
      message: >-
        bad pattern found!
      languages: [generic]
      severity: ERROR
    """
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *semgrep_rules(),
            *semgrep_subsystem_rules(),
            *dependency_inference_rules(),
            *source_files.rules(),
            QueryRule(Partitions, (SemgrepRequest.PartitionRequest,)),
            QueryRule(LintResult, (SemgrepRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[SemgrepRuleSource, SemgrepRuleSourcesGeneratorTarget, FileTarget],
    )


def run_semgrep(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: Sequence[str] = (),
) -> tuple[LintResult, ...]:
    rule_runner.set_options(["--backend-packages=pants.backend.tools.semgrep", *extra_args])
    partitions = rule_runner.request(
        Partitions[SemgrepFieldSet, PartitionMetadata],
        [SemgrepRequest.PartitionRequest(tuple(SemgrepFieldSet.create(tgt) for tgt in targets))],
    )

    return tuple(
        rule_runner.request(
            LintResult, [SemgrepRequest.Batch("", partition.elements, partition.metadata)]
        )
        for partition in partitions
    )


def assert_success(
    rule_runner: RuleRunner, target: Target, *, extra_args: Sequence[str] = ()
) -> None:
    result = run_semgrep(rule_runner, [target], extra_args=extra_args)

    assert len(result) == 1
    assert "FIXME FIXME" in result[0].stdout
    assert result[0].exit_code == 0
    assert result[0].report == EMPTY_DIGEST


@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(Semgrep.default_interpreter_constraints),
)
def test_passing(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files(
        {
            f"{DIR}/file.txt": GOOD_FILE,
            f"{DIR}/.semgrep.yml": RULES,
            f"{DIR}/BUILD": dedent(
                """\
                file(name="f", source="file.txt")
                semgrep_rule_sources(name="s")
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address(DIR, target_name="f"))
    assert_success(
        rule_runner,
        tgt,
        extra_args=[f"--python-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )
