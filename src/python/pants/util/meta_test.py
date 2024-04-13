# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod

import pytest

from pants.util.meta import SingletonMetaclass, classproperty
from pants.util.strutil import softwrap


def test_singleton() -> None:
    class One(metaclass=SingletonMetaclass):
        pass

    assert One() is One()


class WithProp:
    _value = "val0"

    @classproperty
    def class_property(cls):
        """class_property docs."""
        return cls._value

    @classmethod
    def class_method(cls):
        return cls._value

    @staticmethod
    def static_method():
        return "static_method"


class OverridingValueField(WithProp):
    _value = "val1"


class OverridingValueInit(WithProp):
    """Override the class-level `_value` with an instance-level `_value` from a constructor.

    The class-level methods should still return the class-level `_value`, but the new instance
    methods should return the value from the constructor.
    """

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
    _other_value = "o0"

    @classproperty
    def class_property(cls):
        return super().class_property + cls._other_value


def test_access() -> None:
    assert "val0" == WithProp.class_property
    assert "val0" == WithProp().class_property

    assert "val0" == WithProp.class_method()
    assert "val0" == WithProp().class_method()

    assert "static_method" == WithProp.static_method()
    assert "static_method" == WithProp().static_method()


def test_has_attr() -> None:
    assert hasattr(WithProp, "class_property") is True
    assert hasattr(WithProp(), "class_property") is True


def test_docstring() -> None:
    assert "class_property docs." == WithProp.__dict__["class_property"].__doc__


def test_override_value() -> None:
    assert "val1" == OverridingValueField.class_property
    assert "val1" == OverridingValueField().class_property


def test_override_inst_value() -> None:
    obj = OverridingValueInit("v1")
    assert "val0" == obj.class_property
    assert "val0" == obj.class_method()
    assert "v1" == obj.instance_property
    assert "v1" == obj.instance_method()


def test_override_inst_method() -> None:
    obj = WithShadowingInstanceMethod("v1")
    assert "v1" == obj.class_property
    assert "v1" == obj.class_method()


def test_override_method_super() -> None:
    assert "val0o0" == OverridingMethodDefSuper.class_property
    assert "val0o0" == OverridingMethodDefSuper().class_property


def test_modify_class_value() -> None:
    class WithFieldToModify:
        _z = "z0"

        @classproperty
        def class_property(cls):
            return cls._z

    assert "z0" == WithFieldToModify.class_property

    # The classproperty reflects the change in state (is not cached by python or something else
    # weird we might do).
    WithFieldToModify._z = "z1"
    assert "z1" == WithFieldToModify.class_property


def test_set_attr():
    class SetValue:
        _x = "x0"

        @classproperty
        def class_property(cls):
            return cls._x

    assert "x0" == SetValue.class_property

    # The @classproperty is gone, this is just a regular property now.
    SetValue.class_property = "x1"
    assert "x1" == SetValue.class_property
    # The source field is unmodified.
    assert "x0" == SetValue._x


def test_delete_attr():
    class DeleteValue:
        _y = "y0"

        @classproperty
        def class_property(cls):
            return cls._y

    assert "y0" == DeleteValue.class_property

    # The @classproperty is gone, but the source field is still alive.
    del DeleteValue.class_property
    assert hasattr(DeleteValue, "class_property") is False
    assert hasattr(DeleteValue, "_y") is True


def test_abstract_classproperty():
    class Abstract(ABC):
        @classproperty
        @property
        @abstractmethod
        def f(cls):
            pass

    with pytest.raises(TypeError) as exc:
        Abstract.f
    assert str(exc.value) == softwrap(
        """
        The classproperty 'f' in type 'Abstract' was an abstractproperty, meaning that type
        Abstract must override it by setting it as a variable in the class body or defining a
        method with an @classproperty decorator.
        """
    )

    class WithoutOverriding(Abstract):
        """Show that subclasses failing to override the abstract classproperty will raise."""

    with pytest.raises(TypeError) as exc:
        WithoutOverriding.f
    assert str(exc.value) == softwrap(
        """
        The classproperty 'f' in type 'WithoutOverriding' was an abstractproperty, meaning that
        type WithoutOverriding must override it by setting it as a variable in the class body or
        defining a method with an @classproperty decorator.
        """
    )

    class Concrete(Abstract):
        f = 3

    assert Concrete.f == 3

    class Concrete2(Abstract):
        @classproperty
        def f(cls):
            return "hello"

    assert Concrete2.f == "hello"
