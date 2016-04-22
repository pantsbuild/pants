# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.arg_splitter import GLOBAL_SCOPE


class OptionsError(Exception):
  """An options system-related error."""


class RegistrationError(OptionsError):
  """An error at option registration time."""

  def __init__(self, msg, scope, option):
    super(RegistrationError, self).__init__(
      '{} [option {} in {}].'.format(msg, option,
      'global scope' if scope == GLOBAL_SCOPE else 'scope {}'.format(scope)))


class ParseError(OptionsError):
  """An error at flag parsing time."""


# Subclasses of RegistrationError. The distinction between them is useful mainly for testing
# that the error we get is the one we expect.
# TODO: Similar thing for ParseError.
def mk_registration_error(msg):
  class Anon(RegistrationError):
    def __init__(self, scope, option, **msg_format_args):
      super(Anon, self).__init__(msg.format(**msg_format_args), scope, option)
  return Anon


BooleanOptionNameWithNo = mk_registration_error('Boolean option names cannot start with --no.')
FrozenRegistration = mk_registration_error('Cannot register an option on a scope after registering '
                                           'on any of its inner scopes.')
ImplicitValIsNone = mk_registration_error('Implicit value cannot be None.')
InvalidKwarg = mk_registration_error('Invalid registration kwarg {kwarg}.')
InvalidMemberType = mk_registration_error('member_type {member_type} not allowed.')
MemberTypeNotAllowed = mk_registration_error('member_type not allowed on option with type {type_}. '
                                             'It may only be specified if type=list.')
NoOptionNames = mk_registration_error('No option names provided.')
OptionAlreadyRegistered = mk_registration_error('An option with this name was already registered '
                                                'on this scope.')
OptionNameDash = mk_registration_error('Option name must begin with a dash.')
OptionNameDoubleDash = mk_registration_error('Long option name must begin with a double-dash.')
RecursiveSubsystemOption = mk_registration_error("Subsystem option cannot specify 'recursive'. "
                                                 "Subsystem options are always recursive.")
Shadowing = mk_registration_error('Option shadows an option in scope {outer_scope}')
