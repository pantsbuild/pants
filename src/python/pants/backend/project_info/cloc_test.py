# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.project_info import cloc
from pants.backend.project_info.cloc import CountLinesOfCode
from pants.backend.python.target_types import PythonLibrary
from pants.core.util_rules import archive, external_tool
from pants.engine.target import Sources, Target
from pants.testutil.test_base import GoalRuleResult, TestBase


class ElixirSources(Sources):
    default = ("*.ex",)


class ElixirTarget(Target):
    alias = "elixir"
    core_fields = (ElixirSources,)


def assert_counts(
    stdout: str, lang: str, *, num_files: int = 1, blank: int = 0, comment: int = 0, code: int = 0
) -> None:
    summary_line = next(
        (
            line
            for line in stdout.splitlines()
            if len(line.split()) == 5 and line.split()[0] == lang
        ),
        None,
    )
    assert summary_line is not None, f"Found no output line for {lang}"
    fields = summary_line.split()
    assert num_files == int(fields[1])
    assert blank == int(fields[2])
    assert comment == int(fields[3])
    assert code == int(fields[4])


class ClocTest(TestBase):
    @classmethod
    def target_types(cls):
        return [PythonLibrary, ElixirTarget]

    @classmethod
    def rules(cls):
        return [*super().rules(), *cloc.rules(), *archive.rules(), *external_tool.rules()]

    def test_cloc(self) -> None:
        py_dir = "src/py/foo"
        self.create_file(
            f"{py_dir}/foo.py", '# A comment.\n\nprint("some code")\n# Another comment.'
        )
        self.create_file(f"{py_dir}/bar.py", '# A comment.\n\nprint("some more code")')
        self.add_to_build_file(py_dir, "python_library()")

        elixir_dir = "src/elixir/foo"
        self.create_file(f"{elixir_dir}/foo.ex", 'IO.puts("Some elixir")\n# A comment')
        self.create_file(
            f"{elixir_dir}/ignored.ex", "# We do not expect this file to appear in counts."
        )
        self.add_to_build_file(elixir_dir, "elixir(sources=['foo.ex'])")

        result = self.run_goal_rule(CountLinesOfCode, args=[py_dir, elixir_dir])
        assert result.exit_code == 0
        assert_counts(result.stdout, "Python", num_files=2, blank=2, comment=3, code=2)
        assert_counts(result.stdout, "Elixir", comment=1, code=1)

    def test_ignored(self) -> None:
        py_dir = "src/py/foo"
        self.create_file(f"{py_dir}/foo.py", "print('some code')")
        self.create_file(f"{py_dir}/empty.py", "")
        self.add_to_build_file(py_dir, "python_library()")

        result = self.run_goal_rule(CountLinesOfCode, args=[py_dir, "--cloc-ignored"])
        assert result.exit_code == 0
        assert "Ignored the following files:" in result.stderr
        assert "empty.py: zero sized file" in result.stderr

    def test_filesystem_specs_with_owners(self) -> None:
        """Even if a file belongs to a target which has multiple sources, we should only run over
        the specified file."""
        py_dir = "src/py/foo"
        self.create_file(f"{py_dir}/foo.py", "print('some code')")
        self.create_file(f"{py_dir}/bar.py", "print('some code')\nprint('more code')")
        self.add_to_build_file(py_dir, "python_library()")
        result = self.run_goal_rule(CountLinesOfCode, args=[f"{py_dir}/foo.py"])
        assert result.exit_code == 0
        assert_counts(result.stdout, "Python", num_files=1, code=1)

    def test_filesystem_specs_without_owners(self) -> None:
        """Unlike most goals, cloc works on any readable file in the build root, regardless of
        whether it's declared in a BUILD file."""
        self.create_file("test/foo.ex", 'IO.puts("im a free thinker!")')
        self.create_file("test/foo.hs", 'main = putStrLn "Whats Pants, precious?"')
        result = self.run_goal_rule(CountLinesOfCode, args=["test/foo.*"])
        assert result.exit_code == 0
        assert_counts(result.stdout, "Elixir", code=1)
        assert_counts(result.stdout, "Haskell", code=1)

    def test_no_sources_exits_gracefully(self) -> None:
        py_dir = "src/py/foo"
        self.add_to_build_file(py_dir, "python_library(sources=[])")
        result = self.run_goal_rule(CountLinesOfCode, args=[py_dir])
        assert result == GoalRuleResult.noop()
