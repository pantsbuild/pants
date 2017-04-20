import conftest
import unittest


class MyTest(unittest.TestCase):
  def test_fixture_ran(self):
    assert 'ok' in conftest.V
