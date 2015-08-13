# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.benchmark_run import BenchmarkRun
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TaskError
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class BenchmarkRunTest(JvmToolTaskTestBase):


  @property
  def alias_groups(self):
    # Aliases appearing in our real BUILD.tools.
    return BuildFileAliases.create(
      targets={
        'jar_library': JarLibrary,
        'java_library': JavaLibrary,
        'python_tests': PythonTests,
      },
      objects={
        'jar': JarDependency,
      },
    )

  @classmethod
  def task_type(cls):
    return BenchmarkRun

  def test_benchmark_complains_on_python_target(self):
    """Run pants against a `python_tests` target. Should execute without error.
    """
    self.add_to_build_file('foo', dedent('''
        python_tests(
          name='hello',
          sources=['some_file.py'],
        )
        '''))

    self.set_options(target='foo:hello')
    context = self.context(target_roots=[self.target('foo:hello')])
    self.populate_compile_classpath(context)

    with self.assertRaises(TaskError):
      self.execute(context)
