# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

from pants.base.deprecated import deprecated
from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo
from pants.subsystem.subsystem import Subsystem
from pants_test.option.util.fakes import (create_option_values_for_optionable,
                                          create_options_for_optionables)


_deprecation_msg = ("Use the for_subsystems and options arguments to BaseTest.context(), or use "
                    "the methods init_subsystem(), global_subsystem_instance() in this module.")


@deprecated('1.4.0', _deprecation_msg)
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
@deprecated('1.4.0', _deprecation_msg)
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


def global_subsystem_instance(subsystem_type, options=None):
  """Returns the global instance of a subsystem, for use in tests.

  :API: public

  :param type subsystem_type: The subclass of :class:`pants.subsystem.subsystem.Subsystem`
                              to create.
  :param options: dict of scope -> (dict of option name -> value).
                  The scopes may be that of the global instance of the subsystem (i.e.,
                  subsystem_type.options_scope) and/or the scopes of instances of the
                  subsystems it transitively depends on.
  """
  init_subsystem(subsystem_type, options)
  return subsystem_type.global_instance()


def init_subsystems(subsystem_types, options=None):
  """Initialize subsystems for use in tests.

  Does not create an instance.  This function is for setting up subsystems that the code
  under test creates.

  Note that there is some redundancy between this function and BaseTest.context(for_subsystems=...).
  TODO: Fix that.

  :API: public

  :param list subsystem_types: The subclasses of :class:`pants.subsystem.subsystem.Subsystem`
                               to create.
  :param options: dict of scope -> (dict of option name -> value).
                  The scopes may be those of the global instances of the subsystems (i.e.,
                  subsystem_type.options_scope) and/or the scopes of instances of the
                  subsystems they transitively depend on.
  """
  for s in subsystem_types:
    if not Subsystem.is_subsystem_type(s):
      raise TypeError('{} is not a subclass of `Subsystem`'.format(s))
  optionables = Subsystem.closure(subsystem_types)
  if options:
    allowed_scopes = {o.options_scope for o in optionables}
    for scope in options.keys():
      if scope not in allowed_scopes:
        raise ValueError('`{}` is not the scope of any of these subsystems: {}'.format(
            scope, optionables))
  # Don't trample existing subsystem options, in case a test has set up some
  # other subsystems in some other way.
  updated_options = dict(Subsystem._options.items()) if Subsystem._options else {}
  if options:
    updated_options.update(options)
  Subsystem.set_options(create_options_for_optionables(optionables, options=updated_options))


def init_subsystem(subsystem_type, options=None):
  """
  Singular form of :func:`pants_test.subsystem.subsystem_util.init_subsystems`

  :API: public

  :param subsystem_type: The subclass of :class:`pants.subsystem.subsystem.Subsystem`
                               to create.
  :param options: dict of scope -> (dict of option name -> value).
                  The scopes may be those of the global instance of the subsystem (i.e.,
                  subsystem_type.options_scope) and/or the scopes of instance of the
                  subsystem it transitively depends on.
  """
  init_subsystems([subsystem_type], options)
