# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.project_info import count_loc
from pants.backend.project_info.count_loc import CountLinesOfCode
from pants.backend.python import target_types_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.core.util_rules import external_tool
from pants.engine.target import MultipleSourcesField, Target
from pants.testutil.rule_runner import GoalRuleResult, RuleRunner


class ElixirSources(MultipleSourcesField):
    default = ("*.ex",)


class ElixirTarget(Target):
    alias = "elixir"
    core_fields = (ElixirSources,)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *count_loc.rules(),
            *external_tool.rules(),
            *target_types_rules.rules(),
        ],
        target_types=[PythonSourcesGeneratorTarget, ElixirTarget],
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


def test_count_loc(rule_runner: RuleRunner) -> None:
    py_dir = "src/py/foo"
    elixir_dir = "src/elixir/foo"
    rule_runner.write_files(
        {
            f"{py_dir}/foo.py": '# A comment.\n\nprint("some code")\n# Another comment.',
            f"{py_dir}/bar.py": '# A comment.\n\nprint("some more code")',
            f"{py_dir}/BUILD": "python_sources(name='lib')",
            f"{elixir_dir}/foo.ex": 'IO.puts("Some elixir")\n# A comment',
            f"{elixir_dir}/ignored.ex": "# We do not expect this file to appear in counts.",
            f"{elixir_dir}/BUILD": "elixir(name='lib', sources=['foo.ex'])",
        }
    )
    result = rule_runner.run_goal_rule(
        CountLinesOfCode, args=[f"{py_dir}:lib", f"{elixir_dir}:lib"]
    )
    assert result.exit_code == 0
    assert_counts(result.stdout, "Python", num_files=2, blank=2, comment=3, code=2)
    assert_counts(result.stdout, "Elixir", comment=1, code=1)


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"foo.py": "print('hello world!')\n", "BUILD": "python_sources(name='foo')"}
    )
    result = rule_runner.run_goal_rule(CountLinesOfCode, args=["//:foo", "--", "--no-cocomo"])
    assert result.exit_code == 0
    assert_counts(result.stdout, "Python", code=1)
    assert "Estimated Cost to Develop" not in result.stdout


def test_files_without_owners(rule_runner: RuleRunner) -> None:
    """Cloc works on any readable file in the build root, regardless of whether it's declared in a
    BUILD file."""
    rule_runner.write_files(
        {
            "test/foo.ex": 'IO.puts("im a free thinker!")',
            "test/foo.hs": 'main = putStrLn "Whats Pants, precious?"',
        }
    )
    result = rule_runner.run_goal_rule(CountLinesOfCode, args=["test/foo.*"])
    assert result.exit_code == 0
    assert_counts(result.stdout, "Elixir", code=1)
    assert_counts(result.stdout, "Haskell", code=1)


def test_no_sources_exits_gracefully(rule_runner: RuleRunner) -> None:
    py_dir = "src/py/foo"
    rule_runner.write_files({f"{py_dir}/BUILD": "python_sources(name='lib')"})
    result = rule_runner.run_goal_rule(CountLinesOfCode, args=[f"{py_dir}:lib"])
    assert result == GoalRuleResult.noop()
