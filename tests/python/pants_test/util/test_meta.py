# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from abc import abstractmethod, abstractproperty
from builtins import object

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
    "class_property docs"
    return cls._value

  @classmethod
  def class_method(cls):
    return cls._value

  @staticproperty
  def static_property():
    "static_property docs"
    return 'static_property'

  @staticmethod
  def static_method():
    return 'static_method'


class OverridingValueField(WithProp):
  _value = 'val1'


class OverridingValueInit(WithProp):
  """Override the class-level `_value` with an instance-level `_value` from a constructor.

  The class-level methods should still return the class-level `_value`, but the new instance methods
  should return the value from the constructor."""

  def __init__(self, v):
    # This will be ignored when accessed as a class method.
    self._value = v

  @property
  def instance_property(self):
    return self._value

  def instance_method(self):
    return self._value


class WithShadowingInstanceMethod(OverridingValueInit):
  """Override the class-level property and method with instance versions.

  The instance-level methods should return the instance-level `_value` (the constructor argument)
  instead of the class-level `_value` (defined in :class:`WithProp`).
  """

  @property
  def class_property(self):
    return self._value

  def class_method(self):
    return self._value


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
    self.assertEqual("class_property docs", WithProp.__dict__['class_property'].__doc__)
    self.assertEqual("static_property docs", WithProp.__dict__['static_property'].__doc__)

  def test_override_value(self):
    self.assertEqual('val1', OverridingValueField.class_property)
    self.assertEqual('val1', OverridingValueField().class_property)

  def test_override_inst_value(self):
    obj = OverridingValueInit('v1')
    self.assertEqual('val0', obj.class_property)
    self.assertEqual('val0', obj.class_method())
    self.assertEqual('v1', obj.instance_property)
    self.assertEqual('v1', obj.instance_method())

  def test_override_inst_method(self):
    obj = WithShadowingInstanceMethod('v1')
    self.assertEqual('v1', obj.class_property)
    self.assertEqual('v1', obj.class_method())

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

  def test_abstract_classproperty(self):
    class Abstract(AbstractClass):
      @classproperty
      @abstractproperty
      def f(cls):
        pass

    with self.assertRaisesWithMessage(TypeError, """\
The classproperty 'f' in type 'Abstract' was an abstractproperty, meaning that type \
Abstract must override it by setting it as a variable in the class body or defining a method \
with an @classproperty decorator."""):
      Abstract.f

    class WithoutOverriding(Abstract):
      """Show that subclasses failing to override the abstract classproperty will raise."""
      pass

    with self.assertRaisesWithMessage(TypeError, """\
The classproperty 'f' in type 'WithoutOverriding' was an abstractproperty, meaning that type \
WithoutOverriding must override it by setting it as a variable in the class body or defining a method \
with an @classproperty decorator."""):
      WithoutOverriding.f

    class Concrete(Abstract):
      f = 3
    self.assertEqual(Concrete.f, 3)

    class Concrete2(Abstract):
      @classproperty
      def f(cls):
        return 'hello'
    self.assertEqual(Concrete2.f, 'hello')
