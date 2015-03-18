# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
from textwrap import dedent

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.address import SyntheticAddress
from pants.base.build_file_aliases import BuildFileAliases
from pants.option.options import Options
from pants.util.dirutil import safe_mkdir
from pants_test.task_test_base import TaskTestBase


class PythonTaskTest(TaskTestBase):
  def setUp(self):
    super(PythonTaskTest, self).setUp()

    # Options that need to be defined for any PythonTask.
    self.set_options_for_scope(Options.GLOBAL_SCOPE, python_chroot_requirements_ttl=None)
    self.set_options(interpreter=None)

    # Re-use the main pants python cache to speed up interpreter selection and artifact resolution.
    safe_mkdir(os.path.join(self.build_root, '.pants.d'))
    shutil.copytree(os.path.join(self.real_build_root, '.pants.d', 'python'),
                    os.path.join(self.build_root, '.pants.d', 'python'),
                    symlinks=True)

  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'python_library': PythonLibrary,
                                            'python_binary': PythonBinary})

  def create_python_library(self, relpath, name, source, contents, dependencies=()):
    self.create_file(relpath=self.build_path(relpath), contents=dedent("""
    python_library(
      name='{name}',
      sources=['__init__.py', '{source}'],
      dependencies=[
        {dependencies}
      ]
    )
    """).format(name=name, source=source, dependencies=','.join(map(repr, dependencies))))

    self.create_file(relpath=os.path.join(relpath, '__init__.py'))
    self.create_file(relpath=os.path.join(relpath, source), contents=contents)
    return self.target(SyntheticAddress(relpath, name).spec)

  def create_python_binary(self, relpath, name, entry_point, dependencies=()):
    self.create_file(relpath=self.build_path(relpath), contents=dedent("""
    python_binary(
      name='{name}',
      entry_point='{entry_point}',
      dependencies=[
        {dependencies}
      ]
    )
    """).format(name=name, entry_point=entry_point, dependencies=','.join(map(repr, dependencies))))

    return self.target(SyntheticAddress(relpath, name).spec)
