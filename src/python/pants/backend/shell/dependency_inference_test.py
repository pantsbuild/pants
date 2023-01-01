# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.shell import dependency_inference
from pants.backend.shell.dependency_inference import (
    InferShellDependencies,
    ParsedShellImports,
    ParseShellImportsRequest,
    ShellDependenciesInferenceFieldSet,
    ShellMapping,
)
from pants.backend.shell.target_types import (
    ShellSourcesGeneratorTarget,
    Shunit2TestsGeneratorTarget,
)
from pants.backend.shell.target_types import rules as target_types_rules
from pants.core.util_rules import external_tool
from pants.engine.addresses import Address
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *dependency_inference.rules(),
            *external_tool.rules(),
            *target_types_rules(),
            QueryRule(ShellMapping, []),
            QueryRule(ParsedShellImports, [ParseShellImportsRequest]),
            QueryRule(InferredDependencies, [InferShellDependencies]),
        ],
        target_types=[ShellSourcesGeneratorTarget, Shunit2TestsGeneratorTarget],
    )


def test_shell_mapping(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            # Two Shell files belonging to the same target. We should use two file addresses.
            "a/f1.sh": "",
            "a/f2.sh": "",
            "a/BUILD": "shell_sources()",
            # >1 target owns the same file, so it's ambiguous.
            "b/f.sh": "",
            "b/BUILD": "shell_sources(name='t1')\nshell_sources(name='t2')",
        }
    )
    result = rule_runner.request(ShellMapping, [])
    assert result == ShellMapping(
        mapping=FrozenDict(
            {
                "a/f1.sh": Address("a", relative_file_path="f1.sh"),
                "a/f2.sh": Address("a", relative_file_path="f2.sh"),
            }
        ),
        ambiguous_modules=FrozenDict(
            {
                "b/f.sh": (
                    Address("b", target_name="t1", relative_file_path="f.sh"),
                    Address("b", target_name="t2", relative_file_path="f.sh"),
                )
            }
        ),
    )


def test_parse_imports(rule_runner: RuleRunner) -> None:
    def parse(content: str) -> set[str]:
        snapshot = rule_runner.make_snapshot({"subdir/f.sh": content})
        return set(
            rule_runner.request(
                ParsedShellImports, [ParseShellImportsRequest(snapshot.digest, "subdir/f.sh")]
            )
        )

    assert not parse("")
    assert not parse("#!/usr/bin/env bash")
    assert not parse("def python():\n  print('hi')")
    assert parse("source a/b.sh") == {"a/b.sh"}
    assert parse(". a/b.sh") == {"a/b.sh"}
    assert parse("source ../parent.sh") == {"../parent.sh"}
    assert parse("echo foo\nsource foo.sh\necho bar; source bar.sh") == {"foo.sh", "bar.sh"}

    # Can use a Shellcheck directive to fix unrecognized imports.
    assert not parse("source ${FOO}")
    assert parse("# shellcheck source=a/b.sh\nsource ${FOO}") == {"a/b.sh"}


def test_dependency_inference(rule_runner: RuleRunner, caplog) -> None:
    rule_runner.write_files(
        {
            "a/f1.sh": dedent(
                """\
                source b/f.sh
                source unknown/f.sh
                """
            ),
            "a/f2.sh": "source a/f1.sh",
            "a/BUILD": "shell_sources()",
            "b/f.sh": "",
            "b/f_test.sh": "source b/f.sh",
            "b/BUILD": "shell_sources()\nshunit2_tests(name='tests', shell='bash')",
            # Test handling of ambiguous imports. We should warn on the ambiguous dependency, but
            # not warn on the disambiguated one and should infer a dep.
            "ambiguous/dep.sh": "",
            "ambiguous/disambiguated.sh": "",
            "ambiguous/main.sh": dedent(
                """\
                source ambiguous/dep.sh
                source ambiguous/disambiguated.sh
                """
            ),
            "ambiguous/BUILD": dedent(
                """\
                shell_sources(name='dep1', sources=['dep.sh', 'disambiguated.sh'])
                shell_sources(name='dep2', sources=['dep.sh', 'disambiguated.sh'])
                shell_sources(
                    name='main',
                    sources=['main.sh'],
                    dependencies=['!./disambiguated.sh:dep2'],
                )
                """
            ),
        }
    )

    def run_dep_inference(address: Address) -> InferredDependencies:
        tgt = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies,
            [InferShellDependencies(ShellDependenciesInferenceFieldSet.create(tgt))],
        )

    assert run_dep_inference(Address("a", relative_file_path="f1.sh")) == InferredDependencies(
        [Address("b", relative_file_path="f.sh")]
    )
    assert run_dep_inference(
        Address("b", target_name="tests", relative_file_path="f_test.sh")
    ) == InferredDependencies([Address("b", relative_file_path="f.sh")])

    caplog.clear()
    assert run_dep_inference(
        Address("ambiguous", target_name="main", relative_file_path="main.sh")
    ) == InferredDependencies(
        [Address("ambiguous", target_name="dep1", relative_file_path="disambiguated.sh")]
    )
    assert len(caplog.records) == 1
    assert "The target ambiguous/main.sh:main sources `ambiguous/dep.sh`" in caplog.text
    assert "['ambiguous/dep.sh:dep1', 'ambiguous/dep.sh:dep2']" in caplog.text
    assert "disambiguated.sh" not in caplog.text
