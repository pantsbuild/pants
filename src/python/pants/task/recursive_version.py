# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class RecursiveVersion(object):
  """Descriptor Class for Task Versions"""

  def __init__(self, value):
    self.value = value

  def __get__(self, obj, type=None):
    """Get method for Descriptor protocol
    Fetch the version for an object and the version of its parents.  If
    a version isn't specified use an _ to indicate a null version.

    We use an _ to indicate non specified versions to differentiate between:
      1.x.2 and 1.2 where the first version is nested 3 classes deep and the
      second only 2

    We use a . to differentiate between cases like 1.11 and 11.1

    Versions will be returned in the following format where where a,b and c are
    presented in resolution order:
    a.b.c
    """
    def has_version(klass):
      return 'version' in klass.__dict__

    if type is None:
      raise AttributeError(
        "Direct invocation of __get__ is not allowed on RecursiveVersion objects"
      )

    parent = type.mro()[1]
    version = str(self.value) if has_version(type) else "_"
    # Stop recursing at object
    if parent is object:
      return version
    else:
      return "{}.{}".format(parent.version, version)
