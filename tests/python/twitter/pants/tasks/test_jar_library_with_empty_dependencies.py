# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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
import unittest

from twitter.pants.base.parse_context import ParseContext
from twitter.pants.base.target import TargetDefinitionException
from twitter.pants.targets.jar_library import JarLibrary


class JarLibraryWithEmptyDependenciesTest(unittest.TestCase):

  def test_empty_dependencies(self):
    with ParseContext.temp():
      JarLibrary("test-jar-library-with-empty-dependencies", [])

  def test_no_dependencies(self):
    with pytest.raises(TargetDefinitionException):
      with ParseContext.temp():
        JarLibrary("test-jar-library-with-empty-dependencies", None)
