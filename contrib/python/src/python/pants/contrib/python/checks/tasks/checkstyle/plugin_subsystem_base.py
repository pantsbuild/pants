# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.subsystem.subsystem import Subsystem


class PluginSubsystemBase(Subsystem):

  @classmethod
  def register_options(cls, register):
    super(PluginSubsystemBase, cls).register_options(register)
    # All checks have this option.
    register('--skip', type=bool,
             help='If enabled, skip this style checker.')

  def get_plugin(self, python_file):
    return self.get_plugin_type()(self.get_options(), python_file)

  def get_plugin_type(self):
    raise NotImplementedError('get_plugin() not implemented in class {}'.format(type(self)))
