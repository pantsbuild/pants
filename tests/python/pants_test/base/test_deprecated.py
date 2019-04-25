# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import warnings
from builtins import object, str
from contextlib import contextmanager

import mock
from packaging.version import Version

from pants.base.deprecated import (BadDecoratorNestingError, BadSemanticVersionError,
                                   CodeRemovedError, InvalidSemanticVersionOrderingError,
                                   MissingSemanticVersionError, NonDevSemanticVersionError,
                                   deprecated, deprecated_conditional, deprecated_module,
                                   warn_or_error)
from pants.util.collections import assert_single_element
from pants_test.test_base import TestBase


_FAKE_CUR_VERSION = '2.0.0.dev0'


class DeprecatedTest(TestBase):
  FUTURE_VERSION = '9999.9.9.dev0'

  @contextmanager
  def _test_deprecation(self, deprecation_expected=True):
    with warnings.catch_warnings(record=True) as seen_warnings:
      def assert_deprecation_warning():
        if deprecation_expected:
          warning = assert_single_element(seen_warnings)
          self.assertEqual(warning.category, DeprecationWarning)
          return warning.message
        else:
          self.assertEqual(0, len(seen_warnings))

      warnings.simplefilter('always')
      self.assertEqual(0, len(seen_warnings))
      yield assert_deprecation_warning
      assert_deprecation_warning()

  def test_deprecated_function(self):
    expected_return = 'deprecated_function'

    @deprecated(self.FUTURE_VERSION)
    def deprecated_function():
      return expected_return

    with self._test_deprecation():
      self.assertEqual(expected_return, deprecated_function())

  def test_deprecated_method(self):
    expected_return = 'deprecated_method'

    class Test(object):
      @deprecated(self.FUTURE_VERSION)
      def deprecated_method(self):
        return expected_return

    with self._test_deprecation():
      self.assertEqual(expected_return, Test().deprecated_method())

  def test_deprecated_conditional_true(self):
    predicate = lambda: True
    with self._test_deprecation():
      deprecated_conditional(predicate, self.FUTURE_VERSION, "test hint message", stacklevel=0)

  def test_deprecated_conditional_false(self):
    predicate = lambda: False
    with self._test_deprecation(deprecation_expected=False):
      deprecated_conditional(predicate, self.FUTURE_VERSION, "test hint message", stacklevel=0)

  def test_deprecated_property(self):
    expected_return = 'deprecated_property'

    class Test(object):
      @property
      @deprecated(self.FUTURE_VERSION)
      def deprecated_property(self):
        return expected_return

    with self._test_deprecation():
      self.assertEqual(expected_return, Test().deprecated_property)

  def test_deprecated_module(self):
    with self._test_deprecation() as extract_deprecation_warning:
      # Note: Attempting to import here a dummy module that just calls deprecated_module() does not
      # properly trigger the deprecation, due to a bad interaction with pytest that I've not fully
      # understood.  But we trust python to correctly execute modules on import, so just testing a
      # direct call of deprecated_module() here is fine.
      deprecated_module(self.FUTURE_VERSION, hint_message='Do not use me.')
      warning_message = str(extract_deprecation_warning())
      self.assertIn('module will be removed', warning_message)
      self.assertIn('Do not use me', warning_message)

  def test_deprecation_hint(self):
    hint_message = 'Find the foos, fast!'
    expected_return = 'deprecated_function'

    @deprecated(self.FUTURE_VERSION, hint_message=hint_message)
    def deprecated_function():
      return expected_return

    with self._test_deprecation() as extract_deprecation_warning:
      self.assertEqual(expected_return, deprecated_function())
      self.assertIn(hint_message, str(extract_deprecation_warning()))

  def test_deprecation_subject(self):
    subject = '`./pants blah`'
    expected_return = 'deprecated_function'

    @deprecated(self.FUTURE_VERSION, subject=subject)
    def deprecated_function():
      return expected_return

    with self._test_deprecation() as extract_deprecation_warning:
      self.assertEqual(expected_return, deprecated_function())
      self.assertIn(subject, str(extract_deprecation_warning()))

  def test_removal_version_required(self):
    with self.assertRaises(MissingSemanticVersionError):
      @deprecated(None)
      def test_func():
        pass

  def test_removal_version_bad(self):
    with self.assertRaises(BadSemanticVersionError):
      warn_or_error('a.a.a', 'dummy description')

    with self.assertRaises(BadSemanticVersionError):
      @deprecated('a.a.a')
      def test_func0():
        pass

    with self.assertRaises(BadSemanticVersionError):
      warn_or_error(1.0, 'dummy description')

    with self.assertRaises(BadSemanticVersionError):
      @deprecated(1.0)
      def test_func1():
        pass

    with self.assertRaises(BadSemanticVersionError):
      warn_or_error('1.a.0', 'dummy description')

    with self.assertRaises(BadSemanticVersionError):
      @deprecated('1.a.0')
      def test_func1a():
        pass

  def test_removal_version_non_dev(self):
    with self.assertRaises(NonDevSemanticVersionError):
      @deprecated('1.0.0')
      def test_func1a():
        pass

  @mock.patch('pants.base.deprecated.PANTS_SEMVER', Version(_FAKE_CUR_VERSION))
  def test_removal_version_same(self):
    with self.assertRaises(CodeRemovedError):
      warn_or_error(_FAKE_CUR_VERSION, 'dummy description')

    @deprecated(_FAKE_CUR_VERSION)
    def test_func():
      pass
    with self.assertRaises(CodeRemovedError):
      test_func()

  def test_removal_version_lower(self):
    with self.assertRaises(CodeRemovedError):
      warn_or_error('0.0.27.dev0', 'dummy description')

    @deprecated('0.0.27.dev0')
    def test_func():
      pass
    with self.assertRaises(CodeRemovedError):
      test_func()

  def test_bad_decorator_nesting(self):
    with self.assertRaises(BadDecoratorNestingError):
      class Test(object):
        @deprecated(self.FUTURE_VERSION)
        @property
        def test_prop(this):
          pass

  def test_deprecation_start_version_validation(self):
    with self.assertRaises(BadSemanticVersionError):
      warn_or_error(removal_version='1.0.0.dev0',
                    deprecated_entity_description='dummy',
                    deprecation_start_version='1.a.0')

    with self.assertRaises(InvalidSemanticVersionOrderingError):
      warn_or_error(removal_version='0.0.0.dev0',
                    deprecated_entity_description='dummy',
                    deprecation_start_version='1.0.0.dev0')

  @mock.patch('pants.base.deprecated.PANTS_SEMVER', Version(_FAKE_CUR_VERSION))
  def test_deprecation_start_period(self):
    with self.assertRaises(CodeRemovedError):
      warn_or_error(removal_version=_FAKE_CUR_VERSION,
                    deprecated_entity_description='dummy',
                    deprecation_start_version='1.0.0.dev0')

    with self.warnings_catcher() as w:
      warn_or_error(removal_version='999.999.999.dev999',
                    deprecated_entity_description='dummy',
                    deprecation_start_version=_FAKE_CUR_VERSION)
      self.assertWarning(w, DeprecationWarning,
                         'DEPRECATED: dummy will be removed in version 999.999.999.dev999.')

    self.assertIsNone(
      warn_or_error(removal_version='999.999.999.dev999',
                    deprecated_entity_description='dummy',
                    deprecation_start_version='500.0.0.dev0'))
