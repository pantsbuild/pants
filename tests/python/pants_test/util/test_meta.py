# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod, abstractproperty

from pants.util.meta import AbstractClass, Singleton, classproperty, staticproperty
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
  _value = 'val0'

  @classproperty
  def class_property(cls):
    "some docs"
    return cls._value

  @classmethod
  def class_method(cls):
    return cls._value

  @staticproperty
  def static_property():
    return 'static_property'

  @staticmethod
  def static_method():
    return 'static_method'


class OverridingValueField(WithProp):
  _value = 'val1'


class OverridingValueInit(WithProp):

  def __init__(self, v):
    # This will override the class's _value when evaluating the @classmethod and @classproperty as
    # an instance method/property.
    self._value = v


class OverridingMethodDefSuper(WithProp):

  _other_value = 'o0'

  @classproperty
  def class_property(cls):
    return super(OverridingMethodDefSuper, cls).class_property + cls._other_value


class ClassPropertyTest(TestBase):

  def test_access(self):
    self.assertEqual('val0', WithProp.class_property)
    self.assertEqual('val0', WithProp().class_property)

    self.assertEqual('val0', WithProp.class_method())
    self.assertEqual('val0', WithProp().class_method())

    self.assertEqual('static_property', WithProp.static_property)
    self.assertEqual('static_property', WithProp().static_property)

    self.assertEqual('static_method', WithProp.static_method())
    self.assertEqual('static_method', WithProp().static_method())

  def test_has_attr(self):
    self.assertTrue(hasattr(WithProp, 'class_property'))
    self.assertTrue(hasattr(WithProp(), 'class_property'))

  def test_docstring(self):
    self.assertEqual("some docs", WithProp.__dict__['class_property'].__doc__)

  def test_override_value(self):
    self.assertEqual('val1', OverridingValueField.class_property)
    self.assertEqual('val1', OverridingValueField().class_property)

  def test_override_inst_value(self):
    self.assertEqual('val0', OverridingValueInit('v1').class_property)
    self.assertEqual('val0', OverridingValueInit('v1').class_method())

  def test_override_method_super(self):
    self.assertEqual('val0o0', OverridingMethodDefSuper.class_property)
    self.assertEqual('val0o0', OverridingMethodDefSuper().class_property)

  def test_modify_class_value(self):
    class WithFieldToModify(object):
      _z = 'z0'

      @classproperty
      def class_property(cls):
        return cls._z

    self.assertEqual('z0', WithFieldToModify.class_property)

    # The classproperty reflects the change in state (is not cached by python or something else
    # weird we might do).
    WithFieldToModify._z = 'z1'
    self.assertEqual('z1', WithFieldToModify.class_property)

  def test_set_attr(self):
    class SetValue(object):
      _x = 'x0'

      @staticproperty
      def static_property():
        return 's0'

      @classproperty
      def class_property(cls):
        return cls._x

    self.assertEqual('x0', SetValue.class_property)
    self.assertEqual('s0', SetValue.static_property)

    # The @classproperty is gone, this is just a regular property now.
    SetValue.class_property = 'x1'
    self.assertEqual('x1', SetValue.class_property)
    # The source field is unmodified.
    self.assertEqual('x0', SetValue._x)

    SetValue.static_property = 's1'
    self.assertEqual('s1', SetValue.static_property)

  def test_delete_attr(self):
    class DeleteValue(object):
      _y = 'y0'

      @classproperty
      def class_property(cls):
        return cls._y

      @staticproperty
      def static_property():
        return 's0'

    self.assertEqual('y0', DeleteValue.class_property)
    self.assertEqual('s0', DeleteValue.static_property)

    # The @classproperty is gone, but the source field is still alive.
    del DeleteValue.class_property
    self.assertFalse(hasattr(DeleteValue, 'class_property'))
    self.assertTrue(hasattr(DeleteValue, '_y'))

    del DeleteValue.static_property
    self.assertFalse(hasattr(DeleteValue, 'static_property'))
