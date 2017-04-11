# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.engine.addressable import SubclassesOf, addressable_list
from pants.engine.parser import SymbolTable
from pants.engine.struct import HasProducts, Struct
from pants.engine.subsystem.native import Native
from pants_test.subsystem.subsystem_util import init_subsystem


def init_native():
  """Initialize and return the `Native` subsystem."""
  init_subsystem(Native.Factory)
  return Native.Factory.global_instance().create()


class Target(Struct, HasProducts):
  def __init__(self, name=None, configurations=None, **kwargs):
    super(Target, self).__init__(name=name, **kwargs)
    self.configurations = configurations

  @property
  def products(self):
    return self.configurations

  @addressable_list(SubclassesOf(Struct))
  def configurations(self):
    pass


class TargetTable(SymbolTable):
  @classmethod
  def table(cls):
    return {'struct': Struct, 'target': Target}
