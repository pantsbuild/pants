# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import warnings
from contextlib import contextmanager

import pytest

from pants.base.deprecated import (deprecated, BadDecoratorNestingError, BadRemovalVersionError,
                                   MissingRemovalVersionError, PastRemovalVersionError)
from pants.version import VERSION


FUTURE_VERSION = '9999.9.9'


@contextmanager
def _test_deprecation():
  with warnings.catch_warnings(record=True) as seen_warnings:
    warnings.simplefilter("always")
    assert len(seen_warnings) == 0
    yield seen_warnings
    assert len(seen_warnings) == 1
    warning = seen_warnings[0]
    assert isinstance(warning.message, DeprecationWarning)


def test_deprecated_function():
  expected_return = 'deprecated_function'

  @deprecated(FUTURE_VERSION)
  def deprecated_function():
    return expected_return

  with _test_deprecation():
    assert expected_return == deprecated_function()


def test_deprecated_method():
  expected_return = 'deprecated_method'

  class Test(object):
    @deprecated(FUTURE_VERSION)
    def deprecated_method(self):
      return expected_return

  with _test_deprecation():
    assert expected_return == Test().deprecated_method()


def test_deprecated_property():
  expected_return = 'deprecated_method'

  class Test(object):
    @property
    @deprecated(FUTURE_VERSION)
    def deprecated_property(self):
      return expected_return

  with _test_deprecation():
    assert expected_return == Test().deprecated_property


def test_deprecation_hint():
  hint_message = 'Find the foos, fast!'
  expected_return = 'deprecated_function'

  @deprecated(FUTURE_VERSION, hint_message=hint_message)
  def deprecated_function():
    return expected_return

  with _test_deprecation() as seen_warnings:
    assert expected_return == deprecated_function()
    assert len(seen_warnings) == 1
    warning = seen_warnings[0]
    assert isinstance(warning.message, DeprecationWarning)
    assert hint_message in str(warning.message)


def test_removal_version_required():
  with pytest.raises(MissingRemovalVersionError):
    @deprecated(None)
    def test_func():
      pass


def test_removal_version_bad():
  with pytest.raises(BadRemovalVersionError):
    @deprecated('1.a.0')
    def test_func():
      pass


def test_removal_version_same():
  with pytest.raises(PastRemovalVersionError):
    @deprecated(VERSION)
    def test_func():
      pass


def test_removal_version_too_small():
  with pytest.raises(PastRemovalVersionError):
    @deprecated('0.0.27')
    def test_func():
      pass


def test_bad_decorator_nesting():
  with pytest.raises(BadDecoratorNestingError):
    class Test(object):
      @deprecated(FUTURE_VERSION)
      @property
      def test_prop(self):
        pass
