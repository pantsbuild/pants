# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference import reverse_graph
from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.backend.project_info.dependents import DependentsGoal
from pants.backend.project_info.dependents import rules as dependents_rules
from pants.core.target_types import rules as core_target_types_rules
from pants.testutil.python_rule_runner import PythonRuleRunner

# Edges exercised below: import inference, `__init__.py` inference, explicit `dependencies=[...]`,
# and target-generator -> generated-target edges.
_FILES = {
    "pkg/__init__.py": "VERSION = 1\n",
    "pkg/a.py": "X = 1\n",
    "pkg/b.py": "from pkg.a import X\n",  # import edge b -> a
    "pkg/BUILD": "python_sources()",
    "app/main.py": "from pkg.b import X\n",  # import edge main -> b
    # explicit edge main -> pkg/a.py, plus inferred main -> b
    "app/BUILD": "python_sources(dependencies=['pkg/a.py'])",
}


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    runner = PythonRuleRunner(
        rules=[
            *dependents_rules(),
            *reverse_graph.rules(),
            *dependency_inference_rules.rules(),
            *target_types_rules.rules(),
            *core_target_types_rules(),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )
    return runner


def _dependents(
    rule_runner: PythonRuleRunner,
    target: str,
    *,
    batched: bool,
    transitive: bool,
    extra_global_args: tuple[str, ...] = (),
) -> list[str]:
    global_args = ["--source-root-patterns=['/']", *extra_global_args]
    if batched:
        global_args.append("--dependents-inference-use-batched-python")
    args = (["--transitive"] if transitive else []) + [target]
    result = rule_runner.run_goal_rule(
        DependentsGoal,
        global_args=global_args,
        args=args,
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return sorted(result.stdout.splitlines())


def _assert_equivalent(rule_runner: PythonRuleRunner, targets: list[str]) -> None:
    for target in targets:
        for transitive in (False, True):
            per_target = _dependents(rule_runner, target, batched=False, transitive=transitive)
            batched = _dependents(rule_runner, target, batched=True, transitive=transitive)
            assert per_target == batched, (
                f"Divergence for {target} (transitive={transitive}):\n"
                f"  per-target: {per_target}\n"
                f"  batched:    {batched}"
            )


_QUERY_TARGETS = [
    "pkg/a.py",
    "pkg/b.py",
    "pkg/__init__.py",
    "app/main.py",
    "pkg:pkg",
]


def test_batched_matches_per_target(rule_runner: PythonRuleRunner) -> None:
    """The batched fast path must produce identical results to the per-target algorithm."""
    rule_runner.write_files(_FILES)
    _assert_equivalent(rule_runner, _QUERY_TARGETS)


def test_batched_matches_per_target_empty_init(rule_runner: PythonRuleRunner) -> None:
    """An empty `__init__.py` produces no init dependency (content_only), in both paths."""
    files = dict(_FILES)
    files["pkg/__init__.py"] = ""  # empty -> no init dependency under the default content_only mode
    rule_runner.write_files(files)
    _assert_equivalent(rule_runner, _QUERY_TARGETS)


def test_falls_back_when_ineligible(rule_runner: PythonRuleRunner) -> None:
    """When the batched path can't reproduce a feature (here, asset inference) it must decline and
    the caller's per-target fallback must still produce identical results."""
    rule_runner.write_files(_FILES)
    for target in _QUERY_TARGETS:
        for transitive in (False, True):
            per_target = _dependents(
                rule_runner,
                target,
                batched=False,
                transitive=transitive,
                extra_global_args=("--python-infer-assets",),
            )
            batched = _dependents(
                rule_runner,
                target,
                batched=True,
                transitive=transitive,
                extra_global_args=("--python-infer-assets",),
            )
            assert per_target == batched, f"{target} (transitive={transitive}) diverged via fallback"
