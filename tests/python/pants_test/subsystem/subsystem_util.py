# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.subsystem.subsystem import Subsystem
from pants_test.option.util.fakes import create_options_for_optionables


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
