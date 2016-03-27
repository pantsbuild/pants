# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


def test_constants_only():
  try:
    from pants.constants_only.constants import VALID_IDENTIFIERS # noqa
  except ImportError as e:
    assert False, 'Failed to correctly generate python package: %s' % e
