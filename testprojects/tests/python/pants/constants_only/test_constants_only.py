def test_constants_only():
  try:
    from pants.constants_only.constants import VALID_IDENTIFIERS
  except ImportError as e:
    assert False, 'Failed to correctly generate python package: %s' % e

