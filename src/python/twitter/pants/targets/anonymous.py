# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import OrderedSet


# TODO(John Sirois): this is a fragile duck-type, rationalize a dependency bucket interface
class AnonymousDeps(object):
  def __init__(self):
    self._dependencies = OrderedSet()

  @property
  def dependencies(self):
    return self._dependencies

  def resolve(self):
    for dependency in self.dependencies:
      for dep in dependency.resolve():
        yield dep
