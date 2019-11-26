# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Sequence

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.rules.core import cloc
from pants.testutil.console_rule_test_base import ConsoleRuleTestBase


class ClocTest(ConsoleRuleTestBase):
  goal_cls = cloc.CountLinesOfCode

  @classmethod
  def rules(cls):
    return (*super().rules(), *cloc.rules())

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
    self.create_file('src/py/foo/foo.py', '# A comment.\n\nprint("some code")\n# Another comment.')
    self.create_file('src/py/foo/bar.py', '# A comment.\n\nprint("some more code")')
    self.create_file('src/py/dep/dep.py', 'print("a dependency")')
    self.create_file('src/java/foo/Foo.java', '// A comment. \n class Foo(){}\n')
    self.create_file('src/java/foo/Bar.java', '// We do not expect this file to appear in counts.')

    self.add_to_build_file('src/py/dep', 'python_library(sources=["dep.py"])')
    self.add_to_build_file('src/py/foo', 'python_library(dependencies=["src/py/dep"], sources=["foo.py", "bar.py"])')
    self.add_to_build_file('src/java/foo', 'java_library(sources=["Foo.java"])')

    output = self.execute_rule(args=['src/py/foo', 'src/java/foo']).splitlines()
    self.assert_counts(output, 'Python', num_files=3, blank=2, comment=3, code=3)
    self.assert_counts(output, 'Java', num_files=1, blank=0, comment=1, code=1)

    output = self.execute_rule(args=['src/py/foo', 'src/java/foo', '--fast-cloc-no-transitive']).splitlines()
    self.assert_counts(output, 'Python', num_files=2, blank=2, comment=3, code=2)
    self.assert_counts(output, 'Java', num_files=1, blank=0, comment=1, code=1)

  def test_ignored(self) -> None:
    self.create_file('src/py/foo/foo.py', 'print("some code")')
    self.create_file('src/py/foo/empty.py', '')

    self.add_to_build_file('src/py/foo', 'python_library(sources=["foo.py", "empty.py"])')

    output = self.execute_rule(args=['src/py/foo', '--fast-cloc-ignored'])

    self.assertIn("Ignored the following files:", output)
    self.assertIn("empty.py: zero sized file", output)
