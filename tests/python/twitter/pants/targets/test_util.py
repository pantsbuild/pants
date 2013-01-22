# ==================================================================================================
# Copyright 2013 Foursquare Labs, Inc.
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

__author__ = 'Ryan Williams'

import unittest

class MockPantsTarget(object):
  def __init__(self, spec):
    self.foo = spec

  def __eq__(self, other):
    if not isinstance(other, MockPantsTarget):
      return False
    return self.foo == other.foo

  def __repr__(self):
    return "MockPantsTarget(%s)" % str(self.foo)


from twitter.pants.targets.util import resolve

class ResolveTest(unittest.TestCase):

  def testString(self):
    self.assertEquals(resolve("asdf", clazz=MockPantsTarget).foo, "asdf")

  def testUnicodeString(self):
    self.assertEquals(resolve(u"asdf", clazz=MockPantsTarget).foo, u"asdf")

  def testNone(self):
    self.assertEquals(resolve(None, clazz=MockPantsTarget), None)

  def testPantsTarget(self):
    self.assertEquals(resolve(MockPantsTarget("asdf"), clazz=MockPantsTarget).foo, "asdf")

  def testMixedList(self):
    self.assertEquals(
      resolve([MockPantsTarget("1"), "2", MockPantsTarget("3"), "4", "5"], clazz=MockPantsTarget),
      [MockPantsTarget("1"),
       MockPantsTarget("2"),
       MockPantsTarget("3"),
       MockPantsTarget("4"),
       MockPantsTarget("5")])

  def testNonTarget(self):
    self.assertEquals(
      resolve([MockPantsTarget(1), [4, 'asdf'], "qwer",], clazz=MockPantsTarget),
      [MockPantsTarget(1), [4, MockPantsTarget('asdf')], MockPantsTarget('qwer')])
