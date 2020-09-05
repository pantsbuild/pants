# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.project_info import cloc
from pants.backend.project_info.cloc import CountLinesOfCode
from pants.backend.python.target_types import PythonLibrary
from pants.core.util_rules import external_tool
from pants.engine.target import Sources, Target
from pants.testutil.rule_runner import GoalRuleResult, RuleRunner


class ElixirSources(Sources):
    default = ("*.ex",)


class ElixirTarget(Target):
    alias = "elixir"
    core_fields = (ElixirSources,)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[*cloc.rules(), *external_tool.rules()], target_types=[PythonLibrary, ElixirTarget]
    )


def assert_counts(
    stdout: str, lang: str, *, num_files: int = 1, blank: int = 0, comment: int = 0, code: int = 0
) -> None:
    summary_line = next(
        (
            line
            for line in stdout.splitlines()
            if len(line.split()) in (6, 7) and line.split()[0] == lang
        ),
        None,
    )
    assert summary_line is not None, f"Found no output line for {lang} given stdout:\n {stdout}"
    fields = summary_line.split()
    assert num_files == int(fields[1])
    assert blank == int(fields[3])
    assert comment == int(fields[4])
    assert code == int(fields[5])


def test_cloc(rule_runner: RuleRunner) -> None:
    py_dir = "src/py/foo"
    rule_runner.create_file(
        f"{py_dir}/foo.py", '# A comment.\n\nprint("some code")\n# Another comment.'
    )
    rule_runner.create_file(f"{py_dir}/bar.py", '# A comment.\n\nprint("some more code")')
    rule_runner.add_to_build_file(py_dir, "python_library()")

    elixir_dir = "src/elixir/foo"
    rule_runner.create_file(f"{elixir_dir}/foo.ex", 'IO.puts("Some elixir")\n# A comment')
    rule_runner.create_file(
        f"{elixir_dir}/ignored.ex", "# We do not expect this file to appear in counts."
    )
    rule_runner.add_to_build_file(elixir_dir, "elixir(sources=['foo.ex'])")

    result = rule_runner.run_goal_rule(CountLinesOfCode, args=[py_dir, elixir_dir])
    assert result.exit_code == 0
    assert_counts(result.stdout, "Python", num_files=2, blank=2, comment=3, code=2)
    assert_counts(result.stdout, "Elixir", comment=1, code=1)


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.create_file("foo.py", "print('hello world!')\n")
    rule_runner.add_to_build_file("", "python_library(name='foo')")
    result = rule_runner.run_goal_rule(CountLinesOfCode, args=["--args='--no-cocomo'", "//:foo"])
    assert result.exit_code == 0
    assert_counts(result.stdout, "Python", code=1)
    assert "Estimated Cost to Develop" not in result.stdout


def test_files_without_owners(rule_runner: RuleRunner) -> None:
    """cloc works on any readable file in the build root, regardless of whether it's declared in a
    BUILD file."""
    rule_runner.create_file("test/foo.ex", 'IO.puts("im a free thinker!")')
    rule_runner.create_file("test/foo.hs", 'main = putStrLn "Whats Pants, precious?"')
    result = rule_runner.run_goal_rule(CountLinesOfCode, args=["test/foo.*"])
    assert result.exit_code == 0
    assert_counts(result.stdout, "Elixir", code=1)
    assert_counts(result.stdout, "Haskell", code=1)


def test_no_sources_exits_gracefully(rule_runner: RuleRunner) -> None:
    py_dir = "src/py/foo"
    rule_runner.add_to_build_file(py_dir, "python_library(sources=[])")
    result = rule_runner.run_goal_rule(CountLinesOfCode, args=[py_dir])
    assert result == GoalRuleResult.noop()
