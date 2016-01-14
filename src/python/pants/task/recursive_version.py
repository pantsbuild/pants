# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class RecursiveVersion(object):
  """Descriptor Class for Task Versions

  This is used to describe the version attribute on a class.

  Ex:
    class Foo(object):
      version = RecursiveVersion(1)


    class Bar(Foo):
      pass


    class Baz(Bar):
      version = RecursiveVersion(2)

    o = Baz()
    assert o.version == '1._.2'
  """

  def __init__(self, value):
    self.value = str(value)

  def __get__(self, obj, obj_type=None):
    """Get method for Descriptor protocol
    Fetch the version for an object and the version of its parents.  If
    a version isn't specified use an _ to indicate a null version.

    We use an _ to indicate non specified versions to differentiate between:
      1._.2 and 1.2 where the first version is nested 3 classes deep and the
      second only 2.

    We use a . to differentiate between cases like 1.11 and 11.1.

    Versions will be returned in the following format where where a, b and c are
    presented in resolution order:
    a.b.c
    """
    def class_version(klass):
      """Ensure that if version isn't specified we return a value to avoid ambigous versions"""
      if 'version' in klass.__dict__:
        return klass.version
      else:
        return '_'

    # self is the instance of the descriptor. obj is instance its attached to.
    mro = type(obj).mro()

    # Ignore self and object from MRO to get parents.
    parents = [klass for klass in mro[1:-1]]
    parent_versions = map(class_version, parents)
    if 'version' in obj_type.__dict__:
      cur = self.value
    else:
      cur = '_'
    versions = [cur] + parent_versions
    return ".".join(map(str, reversed(versions)))
