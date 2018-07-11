# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from abc import ABCMeta
from builtins import object


class SingletonMetaclass(type):
  """Singleton metaclass."""

  def __call__(cls, *args, **kwargs):
    if not hasattr(cls, 'instance'):
      cls.instance = super(SingletonMetaclass, cls).__call__(*args, **kwargs)
    return cls.instance


class ClassPropertyDescriptor(object):
  """Define a readable class property, given a function."""

  # TODO: it seems overriding __set__ and __delete__ would require defining a metaclass or
  # overriding __setattr__/__delattr__ (see
  # https://stackoverflow.com/questions/5189699/how-to-make-a-class-property). The current solution
  # doesn't require any modifications to the class definition beyond declaring a @classproperty.  If
  # we can set __delete__ and have it work, we can use that e.g. to clear the cache for a new
  # `@memoized_classproperty` decorator.
  def __init__(self, fget, doc):
    self.fget = fget
    self.__doc__ = doc

  # See https://docs.python.org/2/howto/descriptor.html for more details.
  def __get__(self, obj, objtype=None):
    if objtype is None:
      objtype = type(obj)
    return self.fget.__get__(obj, objtype)()


def classproperty(func):
  """Use as a decorator on a method definition to make it a class-level attribute.

  This decorator can be applied to a method, a classmethod, or a staticmethod. This decorator will
  bind the first argument to the class object.

  Usage:
  >>> class Foo(object):
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
  >>> class Foo(object):
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


# Extend Singleton and your class becomes a singleton, each construction returns the same instance.
try:  # Python3
  Singleton = SingletonMetaclass(u'Singleton', (object,), {})
except TypeError:  # Python2
  Singleton = SingletonMetaclass(b'Singleton', (object,), {})


# Abstract base classes w/o __metaclass__ or meta =, just extend AbstractClass.
try:  # Python3
  AbstractClass = ABCMeta(u'AbstractClass', (object,), {})
except TypeError:  # Python2
  AbstractClass = ABCMeta(b'AbstractClass', (object,), {})
