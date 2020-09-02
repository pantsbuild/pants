# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.python.goals import repl as python_repl
from pants.backend.python.target_types import PythonLibrary
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.pex import PexProcess
from pants.core.goals.repl import Repl
from pants.core.goals.repl import rules as repl_rules
from pants.engine.process import Process
from pants.engine.rules import QueryRule
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *repl_rules(),
            *python_repl.rules(),
            *pex_from_targets.rules(),
            QueryRule(Process, (PexProcess, OptionsBootstrapper)),
        ],
        target_types=[PythonLibrary, ProtobufLibrary],
    )


def setup_sources(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file("src/python", "protobuf_library(name='proto')\n")
    rule_runner.add_to_build_file("src/python", "python_library(dependencies=[':proto'])\n")
    rule_runner.create_file("src/python/foo.proto", 'syntax = "proto3";message Foo {}')
    rule_runner.create_file("src/python/lib.py", "from foo import Foo\nclass SomeClass:\n  pass\n")


def test_repl_with_targets(rule_runner: RuleRunner) -> None:
    # TODO(#9108): A mock InteractiveRunner that allows us to actually run code in
    #  the repl and verify that, e.g., the generated protobuf code is available.
    #  Right now this test prepares for that by including generated code, but cannot
    #  actually verify it.
    setup_sources(rule_runner)
    result = rule_runner.run_goal_rule(
        Repl,
        global_args=[
            "--backend-packages=pants.backend.python",
            "--backend-packages=pants.backend.codegen.protobuf.python",
        ],
        args=["src/python/lib.py"],
    )
    assert result.exit_code == 0


def test_repl_ipython(rule_runner: RuleRunner) -> None:
    setup_sources(rule_runner)
    result = rule_runner.run_goal_rule(
        Repl,
        global_args=[
            "--backend-packages=pants.backend.python",
            "--backend-packages=pants.backend.codegen.protobuf.python",
        ],
        args=["--shell=ipython", "src/python/lib.py"],
    )
    assert result.exit_code == 0


def test_repl_bogus_repl_name(rule_runner: RuleRunner) -> None:
    setup_sources(rule_runner)
    result = rule_runner.run_goal_rule(
        Repl,
        global_args=["--backend-packages=pants.backend.python"],
        args=["--shell=bogus-repl", "src/python/lib.py"],
    )
    assert result.exit_code == -1
    assert "'bogus-repl' is not a registered REPL. Available REPLs" in result.stderr
