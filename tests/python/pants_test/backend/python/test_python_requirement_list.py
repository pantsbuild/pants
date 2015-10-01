# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.base_test import BaseTest


class PythonRequirementListTest(BaseTest):
  @property
  def alias_groups(self):
    return BuildFileAliases(
        targets={
            'python_requirement_library': PythonRequirementLibrary,
        },
        objects={
            'python_requirement': PythonRequirement,
        },
    )

  def test_bad_list(self):
    self.add_to_build_file(
        'lib',
        dedent('''
          python_requirement_library(
            name='pyunit',
            requirements=[
              'argparse==1.2.1'
            ]
          )
        '''))
    with self.assertRaises(ValueError):
      self.target('lib:pyunit')

  def test_good_list(self):
    self.add_to_build_file(
        'lib',
        dedent('''
          python_requirement_library(
            name='pyunit',
            requirements=[
              python_requirement('argparse==1.2.1')
            ]
          )
        '''))

    self.target('lib:pyunit')
