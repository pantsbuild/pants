# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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

__author__ = 'John Sirois'

from twitter.pants.base.generator import TemplateData

import unittest

class TemplateDataTest(unittest.TestCase):
  def setUp(self):
    self.data = TemplateData(foo = 'bar', baz = 42)

  def test_member_access(self):
    try:
      self.data.bip
      self.fail("Access to undefined template data slots should raise")
    except AttributeError:
      # expected
      pass

  def test_member_mutation(self):
    try:
      self.data.baz = 1 / 137
      self.fail("Mutation of a template data's slots should not be allowed")
    except AttributeError:
      # expected
      pass

  def test_extend(self):
    self.assertEqual(self.data.extend(jake = 0.3), TemplateData(baz = 42, foo = 'bar', jake = 0.3))

  def test_equals(self):
    self.assertEqual(self.data, TemplateData(baz = 42).extend(foo = 'bar'))
