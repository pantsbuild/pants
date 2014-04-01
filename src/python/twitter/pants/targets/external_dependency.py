# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod

from twitter.common.lang import AbstractClass


class ExternalDependency(AbstractClass):
  @abstractmethod
  def cache_key(self):
    """
      Returns the key that can uniquely identify this target in the build cache.
    """
