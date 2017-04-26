import unittest

import conftest


class MyTest(unittest.TestCase):
  def test_fixture_ran(self):
    assert 'ok' in conftest.V
