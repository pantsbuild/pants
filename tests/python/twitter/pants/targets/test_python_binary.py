# ==================================================================================================
# Copyright 2013 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import pytest

from twitter.pants.base.parse_context import ParseContext
from twitter.pants.base.target import Target, TargetDefinitionException
from twitter.pants.base_build_root_test import BaseBuildRootTest
from twitter.pants.targets.python_binary import PythonBinary


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
