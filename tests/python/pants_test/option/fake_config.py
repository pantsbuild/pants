# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

class FakeConfig(object):
  """Useful for providing fake config values while testing the options system."""
  def __init__(self, values):
    self._values = values

  def get(self, section, name, default=None):
    if section not in self._values or name not in self._values[section]:
      return default
    return self._values[section][name]

  def getlist(self, section, name, default=None):
    return self.get(section, name, default)
