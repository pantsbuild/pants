# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple

from pants.base import deprecated
from pants.option.option_util import is_list_option


class OptionHelpInfo(namedtuple('_OptionHelpInfo',
    ['registering_class', 'display_args', 'scoped_cmd_line_args', 'unscoped_cmd_line_args',
     'typ', 'fromfile', 'default', 'help', 'deprecated_message', 'removal_version',
     'removal_hint', 'choices'])):
  """A container for help information for a single option.

  registering_class: The type that registered the option.
  display_args: Arg strings suitable for display in help text, including value examples
                (e.g., [-f, --[no]-foo-bar, --baz=<metavar>].)
  scoped_cmd_line_args: The explicitly scoped raw flag names allowed anywhere on the cmd line,
                        (e.g., [--scope-baz, --no-scope-baz, --scope-qux])
  unscoped_cmd_line_args: The unscoped raw flag names allowed on the cmd line in this option's
                          scope context (e.g., [--baz, --no-baz, --qux])
  typ: The type of the option.
  fromfile: `True` if the option supports @fromfile value loading.
  default: The value of this option if no flags are specified (derived from config and env vars).
  help: The help message registered for this option.
  deprecated_message: If deprecated: A message explaining that this option is deprecated at
                      removal_version.
  removal_version: If deprecated: The version at which this option is to be removed.
  removal_hint: If deprecated: The removal hint message registered for this option.
  choices: If this option has a constrained list of choices, a csv list of the choices.
  """

  def comma_separated_display_args(self):
    return ', '.join(self.display_args)


class OptionScopeHelpInfo(namedtuple('_OptionScopeHelpInfo',
                                     ['scope', 'basic', 'recursive', 'advanced'])):
  """A container for help information for a scope of options.

  scope: The scope of the described options.
  basic|recursive|advanced: A list of OptionHelpInfo for the options in that group.
  """
  pass


class HelpInfoExtracter(object):
  """Extracts information useful for displaying help from option registration args."""

  @classmethod
  def get_option_scope_help_info_from_parser(cls, parser):
    """Returns a dict of help information for the options registered on the given parser.

    Callers can format this dict into cmd-line help, HTML or whatever.
    """
    return cls(parser.scope).get_option_scope_help_info(parser.option_registrations_iter())

  @staticmethod
  def compute_default(kwargs):
    """Compute the default value to display in help for an option registered with these kwargs."""
    ranked_default = kwargs.get('default')
    typ = kwargs.get('type', str)

    default = ranked_default.value if ranked_default else None
    if default is None:
      return 'None'

    if typ == list:
      default_str = '[{}]'.format(','.join(["'{}'".format(s) for s in default]))
    elif typ == dict:
      if default:
        default_str = '{{ {} }}'.format(
          ','.join(["'{}':'{}'".format(k, v) for k, v in default.items()]))
      else:
        default_str = '{}'
    elif typ == str:
      default_str = "'{}'".format(default).replace('\n', ' ')
    else:
      default_str = str(default)
    return default_str

  @staticmethod
  def compute_metavar(kwargs):
    """Compute the metavar to display in help for an option registered with these kwargs."""
    metavar = kwargs.get('metavar')
    if not metavar:
      typ = kwargs.get('type', str)
      if typ == list:
        typ = kwargs.get('member_type', str)

      if typ == dict:
        metavar = '"{\'key1\':val1,\'key2\':val2,...}"'
      else:
        metavar = '<{}>'.format(typ.__name__)

    return metavar

  def __init__(self, scope):
    self._scope = scope
    self._scope_prefix = scope.replace('.', '-')

  def get_option_scope_help_info(self, option_registrations_iter):
    """Returns an OptionScopeHelpInfo for the options registered with the (args, kwargs) pairs."""
    basic_options = []
    recursive_options = []
    advanced_options = []
    # Sort the arguments, so we display the help in alphabetical order.
    for args, kwargs in sorted(option_registrations_iter):
      ohi = self.get_option_help_info(args, kwargs)
      if kwargs.get('advanced'):
        advanced_options.append(ohi)
      elif kwargs.get('recursive') and not kwargs.get('recursive_root'):
        recursive_options.append(ohi)
      else:
        basic_options.append(ohi)

    return OptionScopeHelpInfo(scope=self._scope,
                               basic=basic_options,
                               recursive=recursive_options,
                               advanced=advanced_options)

  def get_option_help_info(self, args, kwargs):
    """Returns an OptionHelpInfo for the option registered with the given (args, kwargs)."""
    display_args = []
    scoped_cmd_line_args = []
    unscoped_cmd_line_args = []

    for arg in args:
      is_short_arg = len(arg) == 2
      unscoped_cmd_line_args.append(arg)
      if self._scope_prefix:
        scoped_arg = '--{}-{}'.format(self._scope_prefix, arg.lstrip('-'))
      else:
        scoped_arg = arg
      scoped_cmd_line_args.append(scoped_arg)

      if kwargs.get('type') == bool:
        if is_short_arg:
          display_args.append(scoped_arg)
        else:
          unscoped_cmd_line_args.append('--no-{}'.format(arg[2:]))
          scoped_cmd_line_args.append('--no-{}'.format(scoped_arg[2:]))
          display_args.append('--[no-]{}'.format(scoped_arg[2:]))
      else:
        metavar = self.compute_metavar(kwargs)
        display_arg = '{}={}'.format(scoped_arg, metavar)
        if is_list_option(kwargs):
          # Show the multi-arg append form.
          display_args.append('{arg_str} ({arg_str}) ...'.format(arg_str=display_arg))
          # Also show the list literal form, both with and without the append operator.
          if metavar.startswith('"') and metavar.endswith('"'):
            # We quote the entire list literal, so we shouldn't quote the individual members.
            metavar = metavar[1:-1]
          display_args.append('{arg}="[{metavar}, {metavar}, ...]"'.format(arg=scoped_arg,
                                                                           metavar=metavar))
          display_args.append('{arg}="+[{metavar}, {metavar}, ...]"'.format(arg=scoped_arg,
                                                                            metavar=metavar))
        else:
          display_args.append(display_arg)

    typ = kwargs.get('type', str)
    default = self.compute_default(kwargs)
    help_msg = kwargs.get('help', 'No help available.')
    removal_version = kwargs.get('removal_version')
    deprecated_message = None
    if removal_version:
      deprecated_tense = deprecated.get_deprecated_tense(removal_version)
      deprecated_message = 'DEPRECATED. {} removed in version: {}'.format(deprecated_tense,
                                                                          removal_version)
    removal_hint = kwargs.get('removal_hint')
    choices = ', '.join(kwargs.get('choices')) if kwargs.get('choices') else None

    ret = OptionHelpInfo(registering_class=kwargs.get('registering_class', type(None)),
                         display_args=display_args,
                         scoped_cmd_line_args=scoped_cmd_line_args,
                         unscoped_cmd_line_args=unscoped_cmd_line_args,
                         typ=typ,
                         fromfile=kwargs.get('fromfile', False),
                         default=default,
                         help=help_msg,
                         deprecated_message=deprecated_message,
                         removal_version=removal_version,
                         removal_hint=removal_hint,
                         choices=choices)
    return ret
