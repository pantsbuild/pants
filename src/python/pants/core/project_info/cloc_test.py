# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import PythonLibrary
from pants.backend.jvm.target_types import JavaLibrary
from pants.core.project_info import cloc
from pants.core.util_rules import archive, external_tool
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class ClocTest(GoalRuleTestBase):
    goal_cls = cloc.CountLinesOfCode

    @classmethod
    def target_types(cls):
        return [JavaLibrary, PythonLibrary]

    @classmethod
    def rules(cls):
        return [*super().rules(), *cloc.rules(), *archive.rules(), *external_tool.rules()]

    def assert_counts(
        self,
        stdout: str,
        lang: str,
        *,
        num_files: int = 1,
        blank: int = 0,
        comment: int = 0,
        code: int = 0,
    ) -> None:
        for line in stdout.splitlines():
            fields = line.split()
            if len(fields) < 5 or fields[0] != lang:
                continue
            self.assertEqual(num_files, int(fields[1]))
            self.assertEqual(blank, int(fields[2]))
            self.assertEqual(comment, int(fields[3]))
            self.assertEqual(code, int(fields[4]))
            return
        self.fail(f"Found no output line for {lang}")

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
        self.add_to_build_file(java_dir, "java_library(source='Foo.java')")

        output = self.execute_rule(args=[py_dir, java_dir])
        self.assert_counts(output, "Python", num_files=2, blank=2, comment=3, code=2)
        self.assert_counts(output, "Java", comment=1, code=1)

    def test_ignored(self) -> None:
        py_dir = "src/py/foo"
        self.create_file(f"{py_dir}/foo.py", "print('some code')")
        self.create_file(f"{py_dir}/empty.py", "")
        self.add_to_build_file(py_dir, "python_library()")

        output = self.execute_rule(args=[py_dir, "--cloc2-ignored"])
        assert "Ignored the following files:" in output
        assert "empty.py: zero sized file" in output

    def test_filesystem_specs_with_owners(self) -> None:
        """Even if a file belongs to a target which has multiple sources, we should only run over
        the specified file."""
        py_dir = "src/py/foo"
        self.create_file(f"{py_dir}/foo.py", "print('some code')")
        self.create_file(f"{py_dir}/bar.py", "print('some code')\nprint('more code')")
        self.add_to_build_file(py_dir, "python_library()")
        output = self.execute_rule(args=[f"{py_dir}/foo.py"])
        self.assert_counts(output, "Python", num_files=1, code=1)

    def test_filesystem_specs_without_owners(self) -> None:
        """Unlike most goals, cloc works on any readable file in the build root, regardless of
        whether it's declared in a BUILD file."""
        self.create_file("test/foo.ex", 'IO.puts("im a free thinker!")')
        self.create_file("test/foo.hs", 'main = putStrLn "Whats Pants, precious?"')
        output = self.execute_rule(args=["test/foo.*"])
        self.assert_counts(output, "Elixir", code=1)
        self.assert_counts(output, "Haskell", code=1)

    def test_no_sources_exits_gracefully(self) -> None:
        py_dir = "src/py/foo"
        self.add_to_build_file(py_dir, "python_library(sources=[])")
        output = self.execute_rule(args=[py_dir])
        assert output.strip() == ""
