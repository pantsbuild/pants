import unittest

from twitter.pants.base.target import Target


class BaseMockTargetTest(unittest.TestCase):
  """A baseclass useful for tests using ``MockTarget``s.."""

  def setUp(self):
    Target._clear_all_addresses()
