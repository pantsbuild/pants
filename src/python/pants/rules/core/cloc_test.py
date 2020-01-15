# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Sequence

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.rules.core import cloc
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class ClocTest(GoalRuleTestBase):
  goal_cls = cloc.CountLinesOfCode

  @classmethod
  def rules(cls):
    return super().rules() + cloc.rules()

  @classmethod
  def alias_groups(cls):
    return BuildFileAliases(targets={'java_library': JavaLibrary})

  def assert_counts(self, result: Sequence[str], lang: str, num_files: int, blank: int, comment: int, code: int) -> None:
    for line in result:
      fields = line.split()
      if len(fields) < 5 or fields[0] != lang:
        continue
      self.assertEqual(num_files, int(fields[1]))
      self.assertEqual(blank, int(fields[2]))
      self.assertEqual(comment, int(fields[3]))
      self.assertEqual(code, int(fields[4]))
      return
    self.fail(f'Found no output line for {lang}')

  def test_cloc(self) -> None:
    py_dir = 'src/py/foo'
    self.create_file(f'{py_dir}/foo.py', '# A comment.\n\nprint("some code")\n# Another comment.')
    self.create_file(f'{py_dir}/bar.py', '# A comment.\n\nprint("some more code")')
    self.add_to_build_file(py_dir, 'python_library()')

    java_dir = 'src/java/foo'
    self.create_file(f'{java_dir}/Foo.java', '// A comment. \n class Foo(){}\n')
    self.create_file(f'{java_dir}/Ignored.java', '// We do not expect this file to appear in counts.')
    self.add_to_build_file(java_dir, "java_library(source='Foo.java')")

    output = self.execute_rule(args=[py_dir, java_dir]).splitlines()
    self.assert_counts(output, 'Python', num_files=2, blank=2, comment=3, code=2)
    self.assert_counts(output, 'Java', num_files=1, blank=0, comment=1, code=1)

  def test_ignored(self) -> None:
    py_dir = 'src/py/foo'
    self.create_file(f"{py_dir}/foo.py", "print('some code')")
    self.create_file(f'{py_dir}/empty.py', '')
    self.add_to_build_file(py_dir, 'python_library()')

    output = self.execute_rule(args=[py_dir, '--cloc2-ignored'])
    assert "Ignored the following files:" in output
    assert "empty.py: zero sized file" in output
