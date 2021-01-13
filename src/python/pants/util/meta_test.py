# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod
from dataclasses import FrozenInstanceError, dataclass

import pytest

from pants.util.meta import (
    SingletonMetaclass,
    classproperty,
    decorated_type_checkable,
    frozen_after_init,
    staticproperty,
)


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

    @staticproperty
    def static_property():  # type: ignore[misc]  # MyPy expects methods to have `self` or `cls`
        """static_property docs."""
        return "static_property"

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

    assert "static_property" == WithProp.static_property
    assert "static_property" == WithProp().static_property

    assert "static_method" == WithProp.static_method()
    assert "static_method" == WithProp().static_method()


def test_has_attr() -> None:
    assert hasattr(WithProp, "class_property") is True
    assert hasattr(WithProp(), "class_property") is True


def test_docstring() -> None:
    assert "class_property docs." == WithProp.__dict__["class_property"].__doc__
    assert "static_property docs." == WithProp.__dict__["static_property"].__doc__


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

        @staticproperty
        def static_property():
            return "s0"

        @classproperty
        def class_property(cls):
            return cls._x

    assert "x0" == SetValue.class_property
    assert "s0" == SetValue.static_property

    # The @classproperty is gone, this is just a regular property now.
    SetValue.class_property = "x1"
    assert "x1" == SetValue.class_property
    # The source field is unmodified.
    assert "x0" == SetValue._x

    SetValue.static_property = "s1"
    assert "s1" == SetValue.static_property


def test_delete_attr():
    class DeleteValue:
        _y = "y0"

        @classproperty
        def class_property(cls):
            return cls._y

        @staticproperty
        def static_property():
            return "s0"

    assert "y0" == DeleteValue.class_property
    assert "s0" == DeleteValue.static_property

    # The @classproperty is gone, but the source field is still alive.
    del DeleteValue.class_property
    assert hasattr(DeleteValue, "class_property") is False
    assert hasattr(DeleteValue, "_y") is True

    del DeleteValue.static_property
    assert hasattr(DeleteValue, "static_property") is False


def test_abstract_classproperty():
    class Abstract(ABC):
        @classproperty
        @property
        @abstractmethod
        def f(cls):
            pass

    with pytest.raises(TypeError) as exc:
        Abstract.f
    assert str(exc.value) == (
        "The classproperty 'f' in type 'Abstract' was an abstractproperty, meaning that type "
        "Abstract must override it by setting it as a variable in the class body or defining a "
        "method with an @classproperty decorator."
    )

    class WithoutOverriding(Abstract):
        """Show that subclasses failing to override the abstract classproperty will raise."""

    with pytest.raises(TypeError) as exc:
        WithoutOverriding.f
    assert str(exc.value) == (
        "The classproperty 'f' in type 'WithoutOverriding' was an abstractproperty, meaning that "
        "type WithoutOverriding must override it by setting it as a variable in the class body or "
        "defining a method with an @classproperty decorator."
    )

    class Concrete(Abstract):
        f = 3

    assert Concrete.f == 3

    class Concrete2(Abstract):
        @classproperty
        def f(cls):
            return "hello"

    assert Concrete2.f == "hello"


def test_decorated_type_checkable():
    @decorated_type_checkable
    def f(cls):
        return f.define_instance_of(cls)

    @f
    class C:
        pass

    assert C._decorated_type_checkable_type == type(f)
    assert f.is_instance(C) is True

    # Check that .is_instance() is only true for exactly the decorator @g used on the class D!
    @decorated_type_checkable
    def g(cls):
        return g.define_instance_of(cls)

    @g
    class D:
        pass

    assert D._decorated_type_checkable_type == type(g)
    assert g.is_instance(D) is True
    assert f.is_instance(D) is False


def test_no_init() -> None:
    @frozen_after_init
    class Test:
        pass

    test = Test()
    with pytest.raises(FrozenInstanceError):
        test.x = 1  # type: ignore[attr-defined]


def test_init_still_works() -> None:
    @frozen_after_init
    class Test:
        def __init__(self, x: int) -> None:
            self.x = x
            self.y = "abc"

    test = Test(x=0)
    assert test.x == 0
    assert test.y == "abc"


def test_modify_preexisting_field_after_init() -> None:
    @frozen_after_init
    class Test:
        def __init__(self, x: int) -> None:
            self.x = x

    test = Test(x=0)
    with pytest.raises(FrozenInstanceError):
        test.x = 1


def test_add_new_field_after_init() -> None:
    @frozen_after_init
    class Test:
        def __init__(self, x: int) -> None:
            self.x = x

    test = Test(x=0)
    with pytest.raises(FrozenInstanceError):
        test.y = "abc"  # type: ignore[attr-defined]

    test._unfreeze_instance()  # type: ignore[attr-defined]
    test.y = "abc"  # type: ignore[attr-defined]

    test._freeze_instance()  # type: ignore[attr-defined]
    with pytest.raises(FrozenInstanceError):
        test.z = "abc"  # type: ignore[attr-defined]


def test_explicitly_call_setattr_after_init() -> None:
    @frozen_after_init
    class Test:
        def __init__(self, x: int) -> None:
            self.x = x

    test = Test(x=0)
    with pytest.raises(FrozenInstanceError):
        setattr(test, "x", 1)

    test._unfreeze_instance()  # type: ignore[attr-defined]
    setattr(test, "x", 1)

    test._freeze_instance()  # type: ignore[attr-defined]
    with pytest.raises(FrozenInstanceError):
        test.y = "abc"  # type: ignore[attr-defined]


def test_works_with_dataclass() -> None:
    @frozen_after_init
    @dataclass(frozen=False)
    class Test:
        x: int
        y: str

        def __init__(self, x: int) -> None:
            self.x = x
            self.y = "abc"

    test = Test(x=0)
    with pytest.raises(FrozenInstanceError):
        test.x = 1
