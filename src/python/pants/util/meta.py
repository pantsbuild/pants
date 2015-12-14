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


# Extend Singleton and your class becomes a singleton, each construction returns the same instance.
Singleton = SingletonMetaclass(str('Singleton'), (object,), {})


# Abstract base classes w/o __metaclass__ or meta =, just extend AbstractClass.
AbstractClass = ABCMeta(str('AbstractClass'), (object,), {})
