# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import ABCMeta


class SingletonMetaclass(type):
  """Singleton metaclass."""

  def __call__(cls, *args, **kwargs):
    if not hasattr(cls, 'instance'):
      cls.instance = super(SingletonMetaclass, cls).__call__(*args, **kwargs)
    return cls.instance


class ClassPropertyDescriptor(object):
  """Define a readable class property, given a function."""

  # NB: it seems overriding __set__ and __delete__ require defining a metaclass or overriding
  # __setattr__/__delattr__ (see
  # https://stackoverflow.com/questions/5189699/how-to-make-a-class-property).
  def __init__(self, fget, doc=None):
    self.fget = fget

    if doc is None:
      self.__doc__ = fget.__doc__
    else:
      self.__doc__ = doc

  # See https://docs.python.org/2/howto/descriptor.html for more details.
  def __get__(self, obj, objtype=None):
    if objtype is None:
      objtype = type(obj)
    return self.fget.__get__(obj, objtype)()


def classproperty(func):
  """Use as a decorator on a method definition to access it as a property of the class.

  NB: setting or deleting the attribute of this name will overwrite this property!
  """
  if not isinstance(func, (classmethod, staticmethod)):
    func = classmethod(func)

  return ClassPropertyDescriptor(func)


# Extend Singleton and your class becomes a singleton, each construction returns the same instance.
Singleton = SingletonMetaclass(str('Singleton'), (object,), {})


# Abstract base classes w/o __metaclass__ or meta =, just extend AbstractClass.
AbstractClass = ABCMeta(str('AbstractClass'), (object,), {})
