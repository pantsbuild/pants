# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json

from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized


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


@memoized
def default_subsystem_for_plugin(plugin_type):
  """Create a singleton PluginSubsystemBase subclass for the given plugin type.

  The singleton enforrcement is useful in cases where dependent Tasks are installed multiple times,
  to avoid creating duplicate types which would have option scope collisions.

  :param plugin_type: A CheckstylePlugin subclass.
  :type: :class:`pants.contrib.python.checks.checker.common.CheckstylePlugin`
  :rtype: :class:`pants.contrib.python.checks.tasks.checkstyle.plugin_subsystem_base.PluginSubsystemBase`
  """
  return type(str('{}Subsystem'.format(plugin_type.__name__)),
              (PluginSubsystemBase,),
              {
                str('options_scope'): 'pycheck-{}'.format(plugin_type.name()),
                str('plugin_type'): classmethod(lambda _: plugin_type),
              })
