# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os

from pants.backend.core.wrapped_globs import Globs, RGlobs, ZGlobs
from pants.backend.project_info.tasks.export import Export
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.source_root import SourceRoot
from pants_test.base_test import BaseTest
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class ExportIntegrationTest(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return Export

  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'python_library': PythonLibrary,
      },
      context_aware_object_factories={
        'globs': Globs,
        'rglobs': RGlobs,
        'zglobs': ZGlobs,
      },
    )

  def setUp(self):
    super(ExportIntegrationTest, self).setUp()
    SourceRoot.register(os.path.realpath(os.path.join(self.build_root, 'src')),
                        PythonLibrary)

    self.add_to_build_file('src/x/BUILD', '''
       python_library(name="x", sources=globs("*.py"))
    '''.strip())

    self.add_to_build_file('src/y/BUILD', '''
      python_library(name="y", sources=rglobs("*.py"))
    '''.strip())

    self.add_to_build_file('src/z/BUILD', '''
      python_library(name="z", sources=zglobs("**/*.py"))
    '''.strip())

    self.add_to_build_file('src/exclude/BUILD', '''
      python_library(name="exclude", sources=globs("*.py", exclude=[['foo.py']]))
    '''.strip())

  def test_source_globs(self):
    result = get_json(self.execute_console_task(
      options=dict(globs=True),
      targets=[self.target('src/x')]
    ))

    self.assertEqual(
      {'globs' : ['src/x/*.py',]},
      result['targets']['src/x:x']['globs']
    )

  def test_source_exclude(self):
    result = get_json(self.execute_console_task(
      options=dict(globs=True),
      targets=[self.target('src/exclude')]
    ))

    self.assertEqual(
      {'globs' : ['src/exclude/*.py',],
       'exclude' : [{
         'globs' : ['src/exclude/foo.py']
       }],
     },
      result['targets']['src/exclude:exclude']['globs']
    )

  def test_source_rglobs(self):
    result = get_json(self.execute_console_task(
      options=dict(globs=True),
      targets=[self.target('src/y')]
    ))

    self.assertEqual(
      {'globs' : ['src/y/**/*.py',]},
      result['targets']['src/y:y']['globs']
    )

  def test_source_zglobs(self):
    result = get_json(self.execute_console_task(
      options=dict(globs=True),
      targets=[self.target('src/z')]
    ))

    self.assertEqual(
      {'globs' : ['src/z/**/*.py',]},
      result['targets']['src/z:z']['globs']
    )


def get_json(lines):
  return json.loads(''.join(lines))
