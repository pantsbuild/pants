__author__ = 'Ryan Williams'

import unittest
from twitter.pants.base import Target

class MockPantsTarget(Target):
  def __init__(self, spec):
    self.foo = spec

  def __eq__(self, other):
    return self.foo == other.foo


from twitter.pants.targets.util import resolve

class ResolveTest(unittest.TestCase):

  def testString(self):
    self.assertEquals(resolve("asdf", clazz=MockPantsTarget).foo, "asdf")

  def testNone(self):
    self.assertEquals(resolve(None, clazz=MockPantsTarget), None)

  def testPantsTarget(self):
    self.assertEquals(resolve(MockPantsTarget("asdf"), clazz=MockPantsTarget).foo, "asdf")

  def testMixedList(self):
    self.assertEquals(
      resolve([MockPantsTarget("1"), "2", MockPantsTarget("3"), "4", "5"], clazz=MockPantsTarget),
      [MockPantsTarget("1"), MockPantsTarget("2"), MockPantsTarget("3"), MockPantsTarget("4"), MockPantsTarget("5")])
