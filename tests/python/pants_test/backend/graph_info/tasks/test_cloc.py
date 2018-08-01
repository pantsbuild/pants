# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import filter

from pants.backend.graph_info.tasks.cloc import CountLinesOfCode
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.python.targets.python_library import PythonLibrary
from pants_test.task_test_base import ConsoleTaskTestBase


class ClocTest(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return CountLinesOfCode

  def test_counts(self):
    self.create_file('src/py/foo/foo.py', '# A comment.\n\nprint("some code")\n# Another comment.')
    self.create_file('src/py/foo/bar.py', '# A comment.\n\nprint("some more code")')
    self.create_file('src/py/dep/dep.py', 'print("a dependency")')
    self.create_file('src/java/foo/Foo.java', '// A comment. \n class Foo(){}\n')
    self.create_file('src/java/foo/Bar.java', '// We do not expect this file to appear in counts.')
    dep_py_tgt = self.make_target('src/py/dep', PythonLibrary, sources=['dep.py'])
    py_tgt = self.make_target(
      'src/py/foo',
      PythonLibrary,
      dependencies=[dep_py_tgt],
      sources=['foo.py', 'bar.py'],
    )
    java_tgt = self.make_target('src/java/foo', JavaLibrary, sources=['Foo.java'])

    def assert_counts(res, lang, files, blank, comment, code):
      for line in res:
        fields = line.split()
        if len(fields) >= 5:
          if fields[0] == lang:
            self.assertEqual(files, int(fields[1]))
            self.assertEqual(blank, int(fields[2]))
            self.assertEqual(comment, int(fields[3]))
            self.assertEqual(code, int(fields[4]))
            return
      self.fail('Found no output line for {}'.format(lang))

    res = self.execute_console_task(
      targets=[py_tgt, java_tgt],
      options={'transitive': True},
      scheduler=self.scheduler,
    )
    assert_counts(res, 'Python', files=3, blank=2, comment=3, code=3)
    assert_counts(res, 'Java', files=1, blank=0, comment=1, code=1)

    res = self.execute_console_task(
      targets=[py_tgt, java_tgt],
      options={'transitive': False},
      scheduler=self.scheduler,
    )
    assert_counts(res, 'Python', files=2, blank=2, comment=3, code=2)
    assert_counts(res, 'Java', files=1, blank=0, comment=1, code=1)

  def test_ignored(self):
    self.create_file('src/py/foo/foo.py', 'print("some code")')
    self.create_file('src/py/foo/empty.py', '')
    py_tgt = self.make_target('src/py/foo', PythonLibrary, sources=['foo.py', 'empty.py'])

    res = self.execute_console_task(
      targets=[py_tgt],
      options={'ignored': True},
      scheduler=self.scheduler,
    )
    self.assertEqual(['Ignored the following files:',
                       'src/py/foo/empty.py: zero sized file'],
                      list(filter(None, res))[-2:])
