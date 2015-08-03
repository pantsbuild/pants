# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.subsystem.subsystem import Subsystem
from pants_test.option.util.fakes import create_option_values_for_optionable


def create_subsystem(subsystem_type, scope='test-scope', **options):
  """Creates a Subsystem for test.

  :param type subsystem_type: The subclass of :class:`pants.subsystem.subsystem.Subsystem`
                              to create.
  :param string scope: The scope to create the subsystem in.
  :param **options: Keyword args representing option values explicitly set via the command line.
  """
  if not issubclass(subsystem_type, Subsystem):
    raise TypeError('The given `subsystem_type` was not a subclass of `Subsystem`: {}'
                    .format(subsystem_type))

  option_values = create_option_values_for_optionable(subsystem_type, **options)
  return subsystem_type(scope, option_values)
