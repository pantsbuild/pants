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

import unittest

from twitter.pants.base import ParseContext
from twitter.pants.base.target import Target, TargetDefinitionException


class TargetTest(unittest.TestCase):

  def test_validation(self):
    with ParseContext.temp('TargetTest/test_validation'):
      self.assertRaises(TargetDefinitionException, Target, name=None)
      name = "test"
      self.assertEquals(Target(name=name).name, name)
