# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.codegen.protobuf.target_types import ProtobufSourceTarget
from pants.backend.python.goals import repl as python_repl
from pants.backend.python.subsystems.ipython import rules as ipython_subsystem_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.backend.python.util_rules import local_dists, pex_from_targets
from pants.backend.python.util_rules.pex import PexProcess
from pants.core.goals.repl import Repl
from pants.core.goals.repl import rules as repl_rules
from pants.engine.process import Process
from pants.python.python_setup import PythonSetup
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import GoalRuleResult, QueryRule, RuleRunner, mock_console


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *repl_rules(),
            *ipython_subsystem_rules(),
            *python_repl.rules(),
            *pex_from_targets.rules(),
            *local_dists.rules(),
            QueryRule(Process, (PexProcess,)),
        ],
        target_types=[PythonSourcesGeneratorTarget, ProtobufSourceTarget],
    )
    rule_runner.write_files(
        {
            "src/python/foo.proto": 'syntax = "proto3";message Foo {}',
            "src/python/lib.py": "from foo import Foo\nclass SomeClass:\n  pass\n",
            "src/python/BUILD": (
                "protobuf_source(name='proto', source='foo.proto')\n"
                "python_sources(dependencies=[':proto'])"
            ),
        }
    )
    return rule_runner


def run_repl(rule_runner: RuleRunner, *, extra_args: list[str] | None = None) -> GoalRuleResult:
    # TODO(#9108): Expand `mock_console` to allow for providing input for the repl to verify
    # that, e.g., the generated protobuf code is available. Right now this test prepares for
    # that by including generated code, but cannot actually verify it.
    with mock_console(rule_runner.options_bootstrapper):
        return rule_runner.run_goal_rule(
            Repl,
            global_args=extra_args or (),
            args=["src/python/lib.py"],
            env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        )


def test_default_repl(rule_runner: RuleRunner) -> None:
    assert run_repl(rule_runner).exit_code == 0


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(PythonSetup.default_interpreter_constraints),
)
def test_ipython(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    assert (
        run_repl(
            rule_runner,
            extra_args=[
                "--repl-shell=ipython",
                f"--python-setup-interpreter-constraints=['=={major_minor_interpreter}.*']",
            ],
        ).exit_code
        == 0
    )
