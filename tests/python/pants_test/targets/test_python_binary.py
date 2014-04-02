# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import pytest

from pants.base.parse_context import ParseContext
from pants.base.target import Target, TargetDefinitionException
from pants.targets.python_binary import PythonBinary
from pants_test.base_build_root_test import BaseBuildRootTest


class TestPythonBinary(BaseBuildRootTest):
  def tearDown(self):
    Target._clear_all_addresses()

  def test_python_binary_must_have_some_entry_point(self):
    with ParseContext.temp('src'):
      with pytest.raises(TargetDefinitionException):
        PythonBinary(name = 'binary')

  def test_python_binary_with_entry_point_no_source(self):
    with ParseContext.temp('src'):
      assert PythonBinary(name = 'binary', entry_point = 'blork').entry_point == 'blork'

  def test_python_binary_with_source_no_entry_point(self):
    with ParseContext.temp('src'):
      assert PythonBinary(name = 'binary1', source = 'blork.py').entry_point == 'blork'
      assert PythonBinary(name = 'binary2', source = 'bin/blork.py').entry_point == 'bin.blork'

  def test_python_binary_with_entry_point_and_source(self):
    with ParseContext.temp('src'):
      assert 'blork' == PythonBinary(
          name = 'binary1', entry_point = 'blork', source='blork.py').entry_point
      assert 'blork:main' == PythonBinary(
          name = 'binary2', entry_point = 'blork:main', source='blork.py').entry_point
      assert 'bin.blork:main' == PythonBinary(
          name = 'binary3', entry_point = 'bin.blork:main', source='bin/blork.py').entry_point

  def test_python_binary_with_entry_point_and_source_mismatch(self):
    with ParseContext.temp('src'):
      with pytest.raises(TargetDefinitionException):
        PythonBinary(name = 'binary1', entry_point = 'blork', source='hork.py')
      with pytest.raises(TargetDefinitionException):
        PythonBinary(name = 'binary2', entry_point = 'blork:main', source='hork.py')
      with pytest.raises(TargetDefinitionException):
        PythonBinary(name = 'binary3', entry_point = 'bin.blork', source='blork.py')
      with pytest.raises(TargetDefinitionException):
        PythonBinary(name = 'binary4', entry_point = 'bin.blork', source='bin.py')
