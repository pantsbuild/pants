# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.contrib.python.checks.tasks.checkstyle.plugin_test_base import \
  CheckstylePluginTestBase

from pants.contrib.python.checks.tasks.checkstyle.variable_names import (PEP8VariableNames,
                                                                         allow_underscores,
                                                                         is_builtin_name,
                                                                         is_lower_snake,
                                                                         is_reserved_name,
                                                                         is_reserved_with_trailing_underscore,
                                                                         is_upper_camel)


class PEP8VariableNamesTest(CheckstylePluginTestBase):
  plugin_type = PEP8VariableNames

  def test_allow_underscores(self):
    @allow_underscores(0)
    def no_underscores(name):
      return name
    self.assertEqual('foo', no_underscores('foo'))
    self.assertEqual('foo_', no_underscores('foo_'))
    self.assertFalse(no_underscores('_foo'))
    self.assertFalse(no_underscores('__foo'))

    @allow_underscores(1)
    def one_underscore(name):
      return name
    self.assertEqual('foo', one_underscore('foo'))
    self.assertEqual('foo', one_underscore('_foo'))
    self.assertEqual('foo_', one_underscore('_foo_'))
    self.assertFalse(one_underscore('__foo'))
    self.assertFalse(one_underscore('___foo'))

  UPPER_CAMEL = (
    'Rate',
    'HTTPRate',
    'HttpRate',
    'Justastringofwords'
  )

  LOWER_SNAKE = (
    'quiet',
    'quiet_noises',
  )

  def test_is_upper_camel(self):
    for word in self.UPPER_CAMEL:
      self.assertTrue(is_upper_camel(word))
      self.assertTrue(is_upper_camel('_' + word))
      self.assertFalse(is_upper_camel('__' + word))
      self.assertFalse(is_upper_camel(word + '_'))
    for word in self.LOWER_SNAKE:
      self.assertFalse(is_upper_camel(word))
      self.assertFalse(is_upper_camel('_' + word))
      self.assertFalse(is_upper_camel(word + '_'))

  def test_is_lower_snake(self):
    for word in self.LOWER_SNAKE:
      self.assertTrue(is_lower_snake(word))
      self.assertTrue(is_lower_snake('_' + word))
      self.assertTrue(is_lower_snake('__' + word))
    for word in self.UPPER_CAMEL:
      self.assertFalse(is_lower_snake(word))
      self.assertFalse(is_lower_snake('_' + word))

  def test_is_builtin_name(self):
    self.assertTrue(is_builtin_name('__foo__'))
    self.assertFalse(is_builtin_name('__fo_o__'))
    self.assertFalse(is_builtin_name('__Foo__'))
    self.assertFalse(is_builtin_name('__fOo__'))
    self.assertFalse(is_builtin_name('__foo'))
    self.assertFalse(is_builtin_name('foo__'))

  def test_is_reserved_name(self):
    for name in ('for', 'super', 'id', 'type', 'class'):
      self.assertTrue(is_reserved_name(name))
    self.assertFalse(is_reserved_name('none'))

  def test_is_reserved_with_trailing_underscore(self):
    for name in ('super', 'id', 'type', 'class'):
      self.assertTrue(is_reserved_with_trailing_underscore(name + '_'))
      self.assertFalse(is_reserved_with_trailing_underscore(name + '__'))
    for name in ('garbage', 'slots', 'metaclass'):
      self.assertFalse(is_reserved_with_trailing_underscore(name + '_'))

  def test_class_names(self):
    statement = """
      class dhis_not_right(object):
        pass
    """
    self.assertNit(statement, 'T000', expected_line_number=1)

  def test_class_globals(self):
    statement = """
      class DhisRight(object):
        RIGHT = 123
        notRight = 321
    """
    self.assertNit(statement, 'T001', expected_line_number=3)

  def test_builtin_overrides(self):
    statement = """
      def range():
        print("Not in a class body")

      class DhisRight(object):
        def any(self):
          print("In a class body")
    """
    self.assertNit(statement, 'T801', expected_line_number=1)

  def test_lower_snake_method_names(self):
    statement = """
      def totally_fine():
        print("Not in a class body")

      class DhisRight(object):
        def clearlyNotThinking(self):
          print("In a class body")
    """
    self.assertNit(statement, 'T002', expected_line_number=5)

    statement = """
      class DhisRight:
        def clearlyNotThinking(self):
          print("In a class body")
    """
    self.assertNit(statement, 'T002', expected_line_number=2)

    # Allow derivations from other modules to be ok.
    statement = """
      class TestCase(unittest.TestCase):
        def setUp(self):
          pass
    """
    self.assertNoNits(statement)

    statement = """
      def clearlyNotThinking():
        print("Not in a class body")

      class DhisRight(object):
        def totally_fine(self):
          print("In a class body")
    """
    self.assertNit(statement, 'T002', expected_line_number=1)
