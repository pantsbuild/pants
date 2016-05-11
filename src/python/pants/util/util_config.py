# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re


class UtilConfig(object):
  """Settings that tweak the behavior of functions in pants.util.

  This cannot directly be a subsystem, because it would introduce a dependency cycle between
  utilities and subsystems. So instead this is essentially bag of options with reasonable defaults,
  which a task later initializes. It's a "pretend" subsystem.
  """

  class Configurable(object):
    """A configurable value.

    This is used by the UtilConfigInit to create proper options, whose values are later propagated
    back to this class.
    """

    __name_cleaner = re.compile(r'[^a-zA-Z0-9]+')

    @classmethod
    def clean_name(cls, name):
      return cls.__name_cleaner.sub(' ', name).strip()

    def __init__(self, name, type, help, default=None, advanced=True, parser=None):
      self.init_parameters = dict(
        type=type,
        help=help,
        default=default,
        advanced=advanced,
      )
      self.parser = parser
      self.name = name
      self.current_value = default

    def set_value(self, value):
      parser = self.parser or (lambda x: x)
      self.current_value = parser(value)

    @property
    def variable_name(self):
      return self.clean_name(self.name).replace(' ', '_')

    def matches(self, name):
      return self.clean_name(name) == self.clean_name(self.name)

  configurables = {c.variable_name: c for c in [
    Configurable(name='--temporary-file-mode', type=str,
                 parser=lambda x: int(x.strip(), base=8) if x else None,
                 help='The default permissions mode to use when creating temporary fiels and '
                      'directories.'),
  ]}

  __instance = None

  @classmethod
  def get_options(cls):
    if cls.__instance is None:
      cls.__instance = cls()
    return cls.__instance

  def __getattr__(self, name):
    if name in self.configurables:
      return self.configurables[name].current_value
    raise AttributeError('UtilConfig has no such option: {}'.format(name))

  def __setattr__(self, name, value):
    if name in self.configurables:
      self.configurables[name].set_value(value)
    raise AttributeError('UtilConfig has no such option: {}'.format(name))
