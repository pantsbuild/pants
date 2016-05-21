# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import warnings
from contextlib import contextmanager

import pytest

from pants.base.deprecated import (BadDecoratorNestingError, BadRemovalVersionError,
                                   CodeRemovedError, MissingRemovalVersionError, deprecated,
                                   deprecated_conditional, deprecated_module, warn_or_error)
from pants.version import VERSION


FUTURE_VERSION = '9999.9.9'


@contextmanager
def _test_deprecation(deprecation_expected=True):
  with warnings.catch_warnings(record=True) as seen_warnings:
    def assert_deprecation_warning():
      if deprecation_expected:
        assert len(seen_warnings) == 1
        warning = seen_warnings[0]
        assert isinstance(warning.message, DeprecationWarning)
        return warning.message
      else:
        assert len(seen_warnings) == 0

    warnings.simplefilter('always')
    assert len(seen_warnings) == 0
    yield assert_deprecation_warning
    assert_deprecation_warning()


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


def test_deprecated_conditional_true():
  predicate = lambda: True
  with _test_deprecation():
    deprecated_conditional(predicate, FUTURE_VERSION, "test hint message", stacklevel=0)


def test_deprecated_conditional_false():
  predicate = lambda: False
  with _test_deprecation(deprecation_expected=False):
    deprecated_conditional(predicate, FUTURE_VERSION, "test hint message", stacklevel=0)


def test_deprecated_property():
  expected_return = 'deprecated_property'

  class Test(object):
    @property
    @deprecated(FUTURE_VERSION)
    def deprecated_property(self):
      return expected_return

  with _test_deprecation():
    assert expected_return == Test().deprecated_property


def test_deprecated_module():
  with _test_deprecation() as extract_deprecation_warning:
    # Note: Attempting to import here a dummy module that just calls deprecated_module() does not
    # properly trigger the deprecation, due to a bad interaction with pytest that I've not fully
    # understood.  But we trust python to correctly execute modules on import, so just testing a
    # direct call of deprecated_module() here is fine.
    deprecated_module(FUTURE_VERSION, hint_message='Do not use me.')
    warning_message = str(extract_deprecation_warning())
    assert 'module will be removed' in warning_message
    assert 'Do not use me' in warning_message


def test_deprecation_hint():
  hint_message = 'Find the foos, fast!'
  expected_return = 'deprecated_function'

  @deprecated(FUTURE_VERSION, hint_message=hint_message)
  def deprecated_function():
    return expected_return

  with _test_deprecation() as extract_deprecation_warning:
    assert expected_return == deprecated_function()
    assert hint_message in str(extract_deprecation_warning())


def test_removal_version_required():
  with pytest.raises(MissingRemovalVersionError):
    @deprecated(None)
    def test_func():
      pass


def test_removal_version_bad():
  with pytest.raises(BadRemovalVersionError):
    warn_or_error(1.0, 'dummy description')

  with pytest.raises(BadRemovalVersionError):
    @deprecated(1.0)
    def test_func1():
      pass

  with pytest.raises(BadRemovalVersionError):
    warn_or_error('1.a.0', 'dummy description')

  with pytest.raises(BadRemovalVersionError):
    @deprecated('1.a.0')
    def test_func1a():
      pass


def test_removal_version_same():
  with pytest.raises(CodeRemovedError):
    warn_or_error(VERSION, 'dummy description')

  @deprecated(VERSION)
  def test_func():
    pass
  with pytest.raises(CodeRemovedError):
    test_func()


def test_removal_version_lower():
  with pytest.raises(CodeRemovedError):
    warn_or_error('0.0.27', 'dummy description')

  @deprecated('0.0.27')
  def test_func():
    pass
  with pytest.raises(CodeRemovedError):
    test_func()


def test_bad_decorator_nesting():
  with pytest.raises(BadDecoratorNestingError):
    class Test(object):
      @deprecated(FUTURE_VERSION)
      @property
      def test_prop(self):
        pass
