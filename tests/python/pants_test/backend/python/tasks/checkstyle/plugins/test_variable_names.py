# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.checkstyle.plugins.variable_names import (PEP8VariableNames,
                                                                          allow_underscores,
                                                                          is_builtin_name,
                                                                          is_lower_snake,
                                                                          is_reserved_name,
                                                                          is_reserved_with_trailing_underscore,
                                                                          is_upper_camel)


def test_allow_underscores():
  @allow_underscores(0)
  def no_underscores(name):
    return name
  assert no_underscores('foo') == 'foo'
  assert no_underscores('foo_') == 'foo_'
  assert no_underscores('_foo') is False
  assert no_underscores('__foo') is False

  @allow_underscores(1)
  def one_underscore(name):
    return name
  assert one_underscore('foo') == 'foo'
  assert one_underscore('_foo') == 'foo'
  assert one_underscore('_foo_') == 'foo_'
  assert one_underscore('__foo') is False
  assert one_underscore('___foo') is False


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


def test_is_upper_camel():
  for word in UPPER_CAMEL:
    assert is_upper_camel(word)
    assert is_upper_camel('_' + word)
    assert not is_upper_camel('__' + word)
    assert not is_upper_camel(word + '_')
  for word in LOWER_SNAKE:
    assert not is_upper_camel(word)
    assert not is_upper_camel('_' + word)
    assert not is_upper_camel(word + '_')


def test_is_lower_snake():
  for word in LOWER_SNAKE:
    assert is_lower_snake(word)
    assert is_lower_snake('_' + word)
    assert is_lower_snake('__' + word)
  for word in UPPER_CAMEL:
    assert not is_lower_snake(word)
    assert not is_lower_snake('_' + word)


def test_is_builtin_name():
  assert is_builtin_name('__foo__')
  assert not is_builtin_name('__fo_o__')
  assert not is_builtin_name('__Foo__')
  assert not is_builtin_name('__fOo__')
  assert not is_builtin_name('__foo')
  assert not is_builtin_name('foo__')


def test_is_reserved_name():
  for name in ('for', 'super', 'id', 'type', 'class'):
    assert is_reserved_name(name)
  assert not is_reserved_name('none')


def test_is_reserved_with_trailing_underscore():
  for name in ('super', 'id', 'type', 'class'):
    assert is_reserved_with_trailing_underscore(name + '_')
    assert not is_reserved_with_trailing_underscore(name + '__')
  for name in ('garbage', 'slots', 'metaclass'):
    assert not is_reserved_with_trailing_underscore(name + '_')


def test_class_names():
  p8 = PEP8VariableNames(PythonFile.from_statement("""
    class dhis_not_right(object):
      pass
  """))
  nits = list(p8.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T000'
  assert nits[0]._line_number == 1
  assert nits[0].severity == Nit.ERROR


def test_class_globals():
  p8 = PEP8VariableNames(PythonFile.from_statement("""
    class DhisRight(object):
      RIGHT = 123
      notRight = 321
  """))
  nits = list(p8.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T001'
  assert nits[0]._line_number == 3
  assert nits[0].severity == Nit.ERROR


def test_builtin_overrides():
  p8 = PEP8VariableNames(PythonFile.from_statement("""
    def range():
      print("Not in a class body")
    
    class DhisRight(object):
      def any(self):
        print("In a class body")
  """))
  nits = list(p8.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T801'
  assert nits[0]._line_number == 1
  assert nits[0].severity == Nit.ERROR


def test_lower_snake_method_names():
  p8 = PEP8VariableNames(PythonFile.from_statement("""
    def totally_fine():
      print("Not in a class body")
    
    class DhisRight(object):
      def clearlyNotThinking(self):
        print("In a class body")
  """))
  nits = list(p8.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T002'
  assert nits[0]._line_number == 5
  assert nits[0].severity == Nit.ERROR

  p8 = PEP8VariableNames(PythonFile.from_statement("""
    class DhisRight:
      def clearlyNotThinking(self):
        print("In a class body")
  """))
  nits = list(p8.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T002'
  assert nits[0]._line_number == 2
  assert nits[0].severity == Nit.ERROR

  # Allow derivations from other modules to be ok.
  p8 = PEP8VariableNames(PythonFile.from_statement("""
    class TestCase(unittest.TestCase):
      def setUp(self):
        pass
  """))
  nits = list(p8.nits())
  assert len(list(p8.nits())) == 0

  p8 = PEP8VariableNames(PythonFile.from_statement("""
    def clearlyNotThinking():
      print("Not in a class body")
    
    class DhisRight(object):
      def totally_fine(self):
        print("In a class body")
  """))
  nits = list(p8.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T002'
  assert nits[0]._line_number == 1
  assert nits[0].severity == Nit.ERROR
