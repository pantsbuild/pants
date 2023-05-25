# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.codegen.protobuf.target_types import ProtobufSourceTarget
from pants.backend.python.goals import repl as python_repl
from pants.backend.python.target_types import (
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
)
from pants.backend.python.target_types_rules import rules as target_types_rules
from pants.backend.python.util_rules import local_dists, pex_from_targets
from pants.backend.python.util_rules.pex import PexProcess
from pants.core.goals.generate_lockfiles import NoCompatibleResolveException
from pants.core.goals.repl import Repl
from pants.core.goals.repl import rules as repl_rules
from pants.engine.process import Process
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import GoalRuleResult, QueryRule, engine_error, mock_console


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    rule_runner = PythonRuleRunner(
        rules=[
            *repl_rules(),
            *python_repl.rules(),
            *pex_from_targets.rules(),
            *local_dists.rules(),
            *target_types_rules(),
            QueryRule(Process, (PexProcess,)),
        ],
        target_types=[
            PythonSourcesGeneratorTarget,
            ProtobufSourceTarget,
            PythonSourceTarget,
            PythonRequirementTarget,
        ],
    )
    rule_runner.write_files(
        {
            "src/python/foo.proto": 'syntax = "proto3";message Foo {}',
            "src/python/lib.py": "from foo import Foo\nclass SomeClass:\n  pass\n",
            "src/python/BUILD": dedent(
                """\
                protobuf_source(name='proto', source='foo.proto')
                python_sources(dependencies=[':proto'])
                """
            ),
        }
    )
    return rule_runner


def run_repl(
    rule_runner: PythonRuleRunner, args: list[str], *, global_args: list[str] | None = None
) -> GoalRuleResult:
    # TODO(#9108): Expand `mock_console` to allow for providing input for the repl to verify
    # that, e.g., the generated protobuf code is available. Right now this test prepares for
    # that by including generated code, but cannot actually verify it.
    with mock_console(rule_runner.options_bootstrapper):
        return rule_runner.run_goal_rule(
            Repl,
            global_args=global_args or (),
            args=args,
            env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        )


def test_default_repl(rule_runner: PythonRuleRunner) -> None:
    assert run_repl(rule_runner, ["src/python/lib.py"]).exit_code == 0


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(["CPython>=3.7,<4"]),
)
def test_ipython(rule_runner: PythonRuleRunner, major_minor_interpreter: str) -> None:
    assert (
        run_repl(
            rule_runner,
            ["src/python/lib.py"],
            global_args=[
                "--repl-shell=ipython",
                f"--python-interpreter-constraints=['=={major_minor_interpreter}.*']",
            ],
        ).exit_code
        == 0
    )


def test_eagerly_validate_roots_have_common_resolve(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(name='t1', requirements=[], resolve='a')
                python_source(name='t2', source='f.py', resolve='b')
                """
            )
        }
    )
    with engine_error(NoCompatibleResolveException, contains="pants peek"):
        run_repl(
            rule_runner,
            ["//:t1", "//:t2"],
            global_args=["--python-resolves={'a': '', 'b': ''}", "--python-enable-resolves"],
        )
