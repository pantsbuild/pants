# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.subsystem.subsystem import Subsystem


class GlobalOptions(object):
  """A subsystem that facilitates access to global options."""

  class Factory(Subsystem):
    options_scope = 'global-options'

    def create(self):
      return GlobalOptions(self.global_instance().get_options())

  def __init__(self, global_options):
    self._global_options = global_options

  def get_global_option(self, key):
    """Fetch the value of a specific key from the global options.

    :param key: The key of the option to fetch.
    """
    return getattr(self._global_options, key)

  def get_global_options(self):
    """Fetch the global options in their entirety."""
    return self._global_options
