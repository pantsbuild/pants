# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from abc import abstractmethod, abstractproperty

from pants.util.meta import AbstractClass, Singleton, classproperty
from pants_test.test_base import TestBase


class AbstractClassTest(TestBase):
  def test_abstract_property(self):
    class AbstractProperty(AbstractClass):
      @abstractproperty
      def property(self):
        pass

    with self.assertRaises(TypeError):
      AbstractProperty()

  def test_abstract_method(self):
    class AbstractMethod(AbstractClass):
      @abstractmethod
      def method(self):
        pass

    with self.assertRaises(TypeError):
      AbstractMethod()


class SingletonTest(TestBase):
  def test_singleton(self):
    class One(Singleton):
      pass

    self.assertIs(One(), One())


class WithProp(object):
  _value = 3

  @classproperty
  def f(cls):
    return cls._value


class OverridingValueField(WithProp):
  _value = 4


class OverridingMethodDefSuper(WithProp):

  _other_value = 2

  @classproperty
  def f(cls):
    return super(OverridingMethodDefSuper, cls).f + cls._other_value


class ClassPropertyTest(TestBase):
  def test_access(self):
    self.assertEqual(3, WithProp.f)
    self.assertEqual(3, WithProp().f)

  def test_override_value(self):
    self.assertEqual(4, OverridingValueField.f)
    self.assertEqual(4, OverridingValueField().f)

  def test_override_method_super(self):
    self.assertEqual(5, OverridingMethodDefSuper.f)
    self.assertEqual(5, OverridingMethodDefSuper().f)

  def test_has_attr(self):
    self.assertTrue(hasattr(WithProp, 'f'))
    self.assertTrue(hasattr(WithProp(), 'f'))

  def test_set_attr(self):
    class SetValue(object):
      _x = 3

      @classproperty
      def x(cls):
        return cls._x

    self.assertEqual(3, SetValue.x)

    # The @classproperty is gone, this is just a regular property now.
    SetValue.x = 4
    self.assertEqual(4, SetValue.x)
    # The source field is unmodified.
    self.assertEqual(3, SetValue._x)

  def test_delete_attr(self):
    class DeleteValue(object):
      _y = 45

      @classproperty
      def y(cls):
        return cls._y

    self.assertEqual(45, DeleteValue.y)

    # The @classproperty is gone, but the source field is still alive.
    del DeleteValue.y
    self.assertFalse(hasattr(DeleteValue, 'y'))
    self.assertTrue(hasattr(DeleteValue, '_y'))
