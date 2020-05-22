# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.target_types import JavaLibrary
from pants.backend.project_info import cloc
from pants.backend.python.target_types import PythonLibrary
from pants.core.util_rules import archive, external_tool
from pants.testutil.goal_rule_test_base import GoalRuleResult, GoalRuleTestBase


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


class ClocTest(GoalRuleTestBase):
    goal_cls = cloc.CountLinesOfCode

    @classmethod
    def target_types(cls):
        return [JavaLibrary, PythonLibrary]

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

        java_dir = "src/java/foo"
        self.create_file(f"{java_dir}/Foo.java", "// A comment. \n class Foo(){}\n")
        self.create_file(
            f"{java_dir}/Ignored.java", "// We do not expect this file to appear in counts."
        )
        self.add_to_build_file(java_dir, "java_library(sources=['Foo.java'])")

        result = self.execute_rule(args=[py_dir, java_dir])
        assert_counts(result.stdout, "Python", num_files=2, blank=2, comment=3, code=2)
        assert_counts(result.stdout, "Java", comment=1, code=1)

    def test_ignored(self) -> None:
        py_dir = "src/py/foo"
        self.create_file(f"{py_dir}/foo.py", "print('some code')")
        self.create_file(f"{py_dir}/empty.py", "")
        self.add_to_build_file(py_dir, "python_library()")

        result = self.execute_rule(args=[py_dir, "--cloc-ignored"])
        assert "Ignored the following files:" in result.stderr
        assert "empty.py: zero sized file" in result.stderr

    def test_filesystem_specs_with_owners(self) -> None:
        """Even if a file belongs to a target which has multiple sources, we should only run over
        the specified file."""
        py_dir = "src/py/foo"
        self.create_file(f"{py_dir}/foo.py", "print('some code')")
        self.create_file(f"{py_dir}/bar.py", "print('some code')\nprint('more code')")
        self.add_to_build_file(py_dir, "python_library()")
        result = self.execute_rule(args=[f"{py_dir}/foo.py"])
        assert_counts(result.stdout, "Python", num_files=1, code=1)

    def test_filesystem_specs_without_owners(self) -> None:
        """Unlike most goals, cloc works on any readable file in the build root, regardless of
        whether it's declared in a BUILD file."""
        self.create_file("test/foo.ex", 'IO.puts("im a free thinker!")')
        self.create_file("test/foo.hs", 'main = putStrLn "Whats Pants, precious?"')
        result = self.execute_rule(args=["test/foo.*"])
        assert_counts(result.stdout, "Elixir", code=1)
        assert_counts(result.stdout, "Haskell", code=1)

    def test_no_sources_exits_gracefully(self) -> None:
        py_dir = "src/py/foo"
        self.add_to_build_file(py_dir, "python_library(sources=[])")
        result = self.execute_rule(args=[py_dir])
        assert result == GoalRuleResult.noop()
