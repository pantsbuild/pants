# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


class SingletonMetaclass(type):
  """Singleton metaclass."""

  def __call__(cls, *args, **kwargs):
    # TODO: convert this into an `@memoized_classproperty`!
    if not hasattr(cls, 'instance'):
      cls.instance = super().__call__(*args, **kwargs)
    return cls.instance


class ClassPropertyDescriptor:
  """Define a readable attribute on a class, given a function."""

  # The current solution is preferred as it doesn't require any modifications to the class
  # definition beyond declaring a @classproperty.  It seems overriding __set__ and __delete__ would
  # require defining a metaclass or overriding __setattr__/__delattr__ (see
  # https://stackoverflow.com/questions/5189699/how-to-make-a-class-property).
  def __init__(self, fget, doc):
    self.fget = fget
    self.__doc__ = doc

  # See https://docs.python.org/2/howto/descriptor.html for more details.
  def __get__(self, obj, objtype=None):
    if objtype is None:
      objtype = type(obj)
      # Get the callable field for this object, which may be a property.
    callable_field = self.fget.__get__(obj, objtype)
    if getattr(self.fget.__func__, '__isabstractmethod__', False):
      field_name = self.fget.__func__.fget.__name__
      raise TypeError("""\
The classproperty '{func_name}' in type '{type_name}' was an abstractproperty, meaning that type \
{type_name} must override it by setting it as a variable in the class body or defining a method \
with an @classproperty decorator."""
                      .format(func_name=field_name,
                              type_name=objtype.__name__))
    else:
      return callable_field()


def classproperty(func):
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
    func = classmethod(func)

  return ClassPropertyDescriptor(func, doc)


def staticproperty(func):
  """Use as a decorator on a method definition to make it a class-level attribute (without binding).

  This decorator can be applied to a method or a staticmethod. This decorator does not bind any
  arguments.

  Usage:
  >>> other_x = 'value'
  >>> class Foo:
  ...   @staticproperty
  ...   def x():
  ...     return other_x
  ...
  >>> Foo.x
  'value'

  Setting or deleting the attribute of this name will overwrite this property.

  The docstring of the classproperty `x` for a class `C` can be obtained by
  `C.__dict__['x'].__doc__`.
  """
  doc = func.__doc__

  if not isinstance(func, staticmethod):
    func = staticmethod(func)

  return ClassPropertyDescriptor(func, doc)


# TODO: look into merging this with `enum` and `ChoicesMixin`, which describe a fixed set of
# singletons, to decouple the enum interface from the implementation as a `datatype`.
# Extend Singleton and your class becomes a singleton, each construction returns the same instance.
Singleton = SingletonMetaclass('Singleton', (object,), {})
