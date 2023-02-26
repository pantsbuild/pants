# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import FrozenInstanceError as FrozenInstanceError
from functools import wraps
from typing import Any, Callable, Iterator, Optional, Type, TypeVar, Union

from pants.util.strutil import softwrap

T = TypeVar("T")
C = TypeVar("C", bound=Type)


class SingletonMetaclass(type):
    """When using this metaclass in your class definition, your class becomes a singleton. That is,
    every construction returns the same instance.

    Example class definition:

      class Unicorn(metaclass=SingletonMetaclass):
        pass
    """

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        # TODO: convert this into an `@memoized_classproperty`!
        if not hasattr(cls, "instance"):
            cls.instance = super().__call__(*args, **kwargs)
        return cls.instance


class _ClassPropertyDescriptor:
    """Define a readable attribute on a class, given a function."""

    # The current solution is preferred as it doesn't require any modifications to the class
    # definition beyond declaring a @classproperty.  It seems overriding __set__ and __delete__ would
    # require defining a metaclass or overriding __setattr__/__delattr__ (see
    # https://stackoverflow.com/questions/5189699/how-to-make-a-class-property).
    def __init__(self, fget: Union[classmethod, staticmethod], doc: Optional[str]) -> None:
        self.fget = fget
        self.__doc__ = doc

    # See https://docs.python.org/3/howto/descriptor.html for more details.
    def __get__(self, obj: T, objtype: Optional[Type[T]] = None) -> Any:
        if objtype is None:
            objtype = type(obj)
            # Get the callable field for this object, which may be a property.
        callable_field = self.fget.__get__(obj, objtype)
        if getattr(self.fget.__func__, "__isabstractmethod__", False):
            field_name = self.fget.__func__.fget.__name__  # type: ignore[attr-defined]
            raise TypeError(
                """\
The classproperty '{func_name}' in type '{type_name}' was an abstractproperty, meaning that type \
{type_name} must override it by setting it as a variable in the class body or defining a method \
with an @classproperty decorator.""".format(
                    func_name=field_name, type_name=objtype.__name__
                )
            )
        return callable_field()


def runtime_ignore_subscripts(cls: C) -> C:
    """Use as a decorator on a class to make it subscriptable at runtime, returning the class.

    Generally, this is used inside the `else` of a `TYPE_CHECKING` check.

    Usage:
    >>> if TYPE_CHECKING:
    ...     class MyClass(Generic[...]):
    ...         ...
    ... else:
    ...     @runtime_ignore_subscripts
    ...     class MyClass:
    ...         ...
    ...
    >>> MyClass[int] is MyClass
    True
    """

    @classmethod  # type: ignore[misc]
    def __class_getitem__(cls, item):
        return cls

    cls.__class_getitem__ = __class_getitem__

    return cls


def classproperty(func: Callable[..., T]) -> T:
    """Use as a decorator on a method definition to make it a class-level attribute.

    This decorator can be applied to a method, a classmethod, or a staticmethod. This decorator will
    bind the first argument to the class object.

    Usage:
    >>> class Foo:
    ...   @classproperty
    ...   def name(cls):
    ...     return cls.__name__
    ...
    >>> Foo.name
    'Foo'

    Setting or deleting the attribute of this name will overwrite this property.

    The docstring of the classproperty `x` for a class `C` can be obtained by
    `C.__dict__['x'].__doc__`.
    """
    doc = func.__doc__

    if not isinstance(func, (classmethod, staticmethod)):
        # MyPy complains about converting a Callable -> classmethod. We use a Callable in the first
        # place because there is no typing.classmethod, i.e. a type that takes generic arguments, and
        # we need to use TypeVars for the call sites of this decorator to work properly.
        func = classmethod(func)  # type: ignore[assignment]

    # If we properly annotated this function as returning a _ClassPropertyDescriptor, then MyPy would
    # no longer work correctly at call sites for this decorator.
    return _ClassPropertyDescriptor(func, doc)  # type: ignore[arg-type, return-value]


class _ClassDecoratorWithSentinelAttribute(ABC):
    """Base class to wrap a class decorator which sets a "sentinel attribute".

    This functionality is exposed via the `@decorated_type_checkable` decorator.
    """

    @abstractmethod
    def __call__(self, cls: Type) -> Type:
        ...

    def define_instance_of(self, obj: Type, **kwargs) -> Type:
        return type(obj.__name__, (obj,), {"_decorated_type_checkable_type": type(self), **kwargs})

    def is_instance(self, obj: Type) -> bool:
        return getattr(obj, "_decorated_type_checkable_type", None) is type(self)


def frozen_after_init(cls: C) -> C:
    """Class decorator to freeze any modifications to the object after __init__() is done.

    The primary use case is for @dataclasses who cannot use frozen=True due to the need for a custom
    __init__(), but who still want to remain as immutable as possible (e.g. for safety with the V2
    engine). When using with dataclasses, this should be the first decorator applied, i.e. be used
    before @dataclass.
    """

    # NB: Import inside function and use inner function to avoid circular import
    from pants.base.deprecated import deprecated

    @deprecated(
        removal_version="2.17.0.dev0",
        hint=softwrap(
            """
            Use `frozen=True` and remove `unsafe_hash=True` in your dataclass decorator,
            and `object.__setattr__(self, "attrname", <value>)` in your `__init__`.
            """
        ),
    )
    def frozen_after_init(cls: C) -> C:
        prev_init = cls.__init__
        prev_setattr = cls.__setattr__

        def freeze_instance(self) -> None:
            self._is_frozen = True

        @contextmanager
        def unfrozen(self) -> Iterator:
            old_is_frozen = self._is_frozen
            try:
                self._is_frozen = False
                yield
            finally:
                self._is_frozen = old_is_frozen

        @wraps(prev_init)
        def new_init(self, *args: Any, **kwargs: Any) -> None:
            prev_init(self, *args, **kwargs)
            self._freeze_instance()

        @wraps(prev_setattr)
        def new_setattr(self, key: str, value: Any) -> None:
            if getattr(self, "_is_frozen", False) and key != "_is_frozen":
                raise FrozenInstanceError(
                    f"Attempting to modify the attribute {key} after the object {self} was created."
                )
            prev_setattr(self, key, value)  # type: ignore[call-arg]

        cls._freeze_instance = freeze_instance
        cls._unfrozen = unfrozen
        cls.__init__ = new_init
        cls.__setattr__ = new_setattr  # type: ignore[assignment]

        return cls

    return frozen_after_init(cls)
