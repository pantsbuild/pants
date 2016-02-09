# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo
from pants.subsystem.subsystem import Subsystem
from pants_test.option.util.fakes import (create_option_values_for_optionable,
                                          create_options_for_optionables)


def create_subsystem(subsystem_type, scope='test-scope', **options):
  """Creates a Subsystem for test.

  :API: public

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


@contextmanager
def subsystem_instance(subsystem_type, scope=None, **options):
  """Creates a Subsystem instance for test.

  :API: public

  :param type subsystem_type: The subclass of :class:`pants.subsystem.subsystem.Subsystem`
                              to create.
  :param string scope: An optional scope to create the subsystem in; defaults to global.
  :param **options: Keyword args representing option values explicitly set via the command line.
  """
  if not issubclass(subsystem_type, Subsystem):
    raise TypeError('The given `subsystem_type` was not a subclass of `Subsystem`: {}'
                    .format(subsystem_type))

  optionables = Subsystem.closure([subsystem_type])
  updated_options = dict(Subsystem._options.items()) if Subsystem._options else {}
  if options:
    updated_options.update(options)

  Subsystem._options = create_options_for_optionables(optionables, options=updated_options)
  try:
    if scope is None:
      yield subsystem_type.global_instance()
    else:
      class ScopedOptionable(Optionable):
        options_scope = scope
        options_scope_category = ScopeInfo.SUBSYSTEM
      yield subsystem_type.scoped_instance(ScopedOptionable)
  finally:
    Subsystem.reset()
