# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json

from pants.subsystem.subsystem import Subsystem


class PluginSubsystemBase(Subsystem):
  @classmethod
  def plugin_type(cls):
    raise NotImplementedError('Subclasses must override and return the plugin type the subsystem '
                              'configures.')

  @classmethod
  def register_options(cls, register):
    super(PluginSubsystemBase, cls).register_options(register)
    # All checks have this option.
    register('--skip', type=bool,
             help='If enabled, skip this style checker.')

  def options_blob(self):
    options = self.get_options()
    options_dict = {option: options.get(option) for option in options}
    return json.dumps(options_dict) if options_dict else None


def default_subsystem_for_plugin(plugin_type):
  return type(str('{}Subsystem'.format(plugin_type.__name__)),
              (PluginSubsystemBase,),
              {
                str('options_scope'): 'pycheck-{}'.format(plugin_type.name()),
                str('plugin_type'): classmethod(lambda _: plugin_type),
              })
