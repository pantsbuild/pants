# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import warnings
from argparse import ArgumentParser, _HelpAction
from collections import namedtuple

import six

from pants.base.deprecated import check_deprecated_semver
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.errors import ParseError, RegistrationError
from pants.option.help_formatter import PantsAdvancedHelpFormatter, PantsBasicHelpFormatter
from pants.option.ranked_value import RankedValue


# Standard ArgumentParser prints usage and exits on error. We subclass so we can raise instead.
# Note that subclassing ArgumentParser for this purpose is allowed by the argparse API.
class CustomArgumentParser(ArgumentParser):
  def __init__(self, scope, *args, **kwargs):
    super(CustomArgumentParser, self).__init__(*args, **kwargs)
    self._scope = scope

  def error(self, message):
    scope = 'global' if self._scope == GLOBAL_SCOPE else self._scope
    raise ParseError('{0} in {1} scope'.format(message, scope))

  def walk_actions(self):
    """Iterates over the argparse.Action objects for options registered on this parser."""
    for action_group in self._action_groups:
      for action in action_group._group_actions:
        if not isinstance(action, _HelpAction):
          yield action


class Parser(object):
  """An argument parser in a hierarchy.

  Each node in the hierarchy is a 'scope': the root is the global scope, and the parent of
  a node is the scope it's immediately contained in. E.g., the 'compile.java' scope is
  a child of the 'compile' scope, which is a child of the global scope.

  Options registered on a parser are also registered transitively on all the scopes it encloses.
  Registration must be in outside-in order: we forbid registering options on an outer scope if
  we've already registered an option on one of its inner scopes. This is to ensure that
  re-registering the same option name on an inner scope correctly replaces the identically-named
  option from the outer scope.

  :param env: a dict of environment variables.
  :param config: data from a config file (must support config.get[list](section, name, default=)).
  :param scope: the scope this parser acts for.
  :param parent_parser: the parser for the scope immediately enclosing this one, or
         None if this is the global scope.
  """

  class BooleanConversionError(ParseError):
    """Raised when a value other than 'True' or 'False' is encountered."""
    pass

  class Flag(namedtuple('Flag', ['name', 'inverse_name', 'help_arg'])):
    """A struct describing a single flag and its corresponding help representation.

    No-argument boolean flags also support an `inverse_name` to set the corresponding option value
    in the opposite sense from its default.  All other flags will have no `inverse_name`
    """
    @classmethod
    def _create(cls, flag, **kwargs):
      if kwargs.get('action') in ('store_false', 'store_true') and flag.startswith('--'):
        if flag.startswith('--no-'):
          raise RegistrationError(
            'Invalid flag name "{}". Boolean flag names cannot start with --no-'.format(flag))
        name = flag[2:]
        return cls(flag, '--no-' + name, '--[no-]' + name)
      else:
        return cls(flag, None, flag)

  @classmethod
  def expand_flags(cls, *args, **kwargs):
    """Returns a list of the flags associated with an option registration.

    For example:

      >>> from pants.option.parser import Parser
      >>> def print_flags(flags):
      ...   print('\n'.join(map(str, flags)))
      ...
      >>> print_flags(Parser.expand_flags('-q', '--quiet', action='store_true',
      ...                                 help='Squelches all console output apart from errors.'))
      Flag(name='-q', inverse_name=None, help_arg='-q')
      Flag(name='--quiet', inverse_name=u'--no-quiet', help_arg=u'--[no-]quiet')
      >>>

    :param *args: The args (flag names), that would be passed to an option registration.
    :param **kwargs: The kwargs that would be passed to an option registration.
    """
    return [cls.Flag._create(flag, **kwargs) for flag in args]

  def __init__(self, env, config, scope, help_request, parent_parser):
    self._env = env
    self._config = config
    self._scope = scope
    self._help_request = help_request

    # If True, no more registration is allowed on this parser.
    self._frozen = False

    # The argparser we use for actually parsing args.
    self._argparser = CustomArgumentParser(scope=self._scope, conflict_handler='resolve')

    # The argparser we use for formatting help messages.
    # We don't use self._argparser for this as it will have all options from enclosing scopes
    # registered on it too, which would create unnecessarily repetitive help messages.
    formatter_class = (PantsAdvancedHelpFormatter if help_request and help_request.advanced
                       else PantsBasicHelpFormatter)
    self._help_argparser = CustomArgumentParser(scope=self._scope, conflict_handler='resolve',
                                                formatter_class=formatter_class)

    # Options are registered in two groups.  The first group will always be displayed in the help
    # output.  The second group is for advanced options that are not normally displayed, because
    # they're intended as sitewide config and should not typically be modified by individual users.
    self._help_argparser_group = self._help_argparser.add_argument_group(title=scope)
    self._help_argparser_advanced_group = \
      self._help_argparser.add_argument_group(title='*{0}'.format(scope))

    # If True, we have at least one option to show help for.
    self._has_help_options = False

    # Map of external to internal dest names. See docstring for _set_dest below.
    self._dest_forwardings = {}

    # Keep track of deprecated flags.  Maps flag -> (deprecated_version, deprecated_hint)
    self._deprecated_flags = {}

  # A Parser instance, or None for the global scope parser.
    self._parent_parser = parent_parser

    # List of Parser instances.
    self._child_parsers = []

    if self._parent_parser:
      self._parent_parser._register_child_parser(self)

  @staticmethod
  def str_to_bool(s):
    if isinstance(s, six.string_types):
      if s.lower() == 'true':
        return True
      elif s.lower() == 'false':
        return False
      else:
        raise Parser.BooleanConversionError('Got "{0}". Expected "True" or "False".'.format(s))
    if s is True:
      return True
    elif s is False:
      return False
    else:
      raise Parser.BooleanConversionError('Got {0}. Expected True or False.'.format(s))

  def parse_args(self, args, namespace):
    """Parse the given args and set their values onto the namespace object's attributes."""
    namespace.add_forwardings(self._dest_forwardings)
    new_args = self._argparser.parse_args(args)
    namespace.update(vars(new_args))
    self.deprecated_check(args)
    return namespace

  def format_help(self):
    """Return a help message for the options registered on this object."""
    return self._help_argparser.format_help() if self._has_help_options else ''

  def register(self, *args, **kwargs):
    """Register an option, using argparse params.

    Custom extensions to argparse params:
    :param advanced: if True, the option willally be suppressed when displaying help.
    :param deprecated_version: Mark an option as deprecated.  The value is a semver that indicates
       the release at which the option should be removed from the code.
    :param deprecated_hint: A message to display to the user when displaying help for or invoking
       a deprecated option.
    """
    if self._frozen:
      raise RegistrationError('Cannot register option {0} in scope {1} after registering options '
                              'in any of its inner scopes.'.format(args[0], self._scope))

    # Prevent further registration in enclosing scopes.
    ancestor = self._parent_parser
    while ancestor:
      ancestor._freeze()
      ancestor = ancestor._parent_parser

    # Pull out our custom arguments, they aren't valid for argparse.
    recursive = kwargs.pop('recursive', False)
    advanced = kwargs.pop('advanced', False)

    self._validate(args, kwargs)
    dest = self._set_dest(args, kwargs)

    deprecated_version = kwargs.pop('deprecated_version', None)
    deprecated_hint = kwargs.pop('deprecated_hint', '')

    if deprecated_version is not None:
      check_deprecated_semver(deprecated_version)
      flag = '--' + dest.replace('_', '-')
      self._deprecated_flags[flag] = (deprecated_version, deprecated_hint)
      help = kwargs.pop('help', '')
      kwargs['help'] = 'DEPRECATED: {}\n{}'.format(self.deprecated_message(flag), help)

    inverse_args = []
    help_args = []
    for flag in self.expand_flags(*args, **kwargs):
      if flag.inverse_name:
        inverse_args.append(flag.inverse_name)
        if deprecated_version:
          self._deprecated_flags[flag.inverse_name] = (deprecated_version, deprecated_hint)
      help_args.append(flag.help_arg)
    is_invertible = len(inverse_args) > 0

    # Register the option, only on this scope, for the purpose of displaying help.
    # Note that we'll only display the default value for this scope, even though the
    # default may be overridden in inner scopes.
    raw_default = self._compute_default(dest, is_invertible, kwargs).value
    kwargs_with_default = dict(kwargs, default=raw_default)

    if advanced:
      arg_group = self._help_argparser_advanced_group
    else:
      arg_group = self._help_argparser_group
    arg_group.add_argument(*help_args, **kwargs_with_default)

    self._has_help_options = True

    # Register the option for the purpose of parsing, on this and all enclosed scopes.
    if is_invertible:
      inverse_kwargs = self._create_inverse_kwargs(kwargs)
      self._register_boolean(dest, args, kwargs, inverse_args, inverse_kwargs, recursive)
    else:
      self._register(dest, args, kwargs, recursive)

  def is_deprecated(self, flag):
    """Returns True if the flag has been marked as deprecated with 'deprecated_version'.

    :param flag: flag to test  (if it starts with --{scope}-, or --no-{scope}, the scope will be
    stripped out)
    """
    flag = flag.split('=')[0]
    if flag.startswith('--{}-'.format(self._scope)):
      flag = '--{}'.format(flag[3 + len(self._scope):])  # strip off the --{scope}- prefix
    elif flag.startswith('--no-{}-'.format(self._scope)):
      flag = '--no-{}'.format(flag[6 + len(self._scope):])  # strip off the --no-{scope}- prefix

    return flag in self._deprecated_flags

  def deprecated_message(self, flag):
    """Returns the message to be displayed when a deprecated flag is invoked or asked for help.

    The caller must insure that the flag has already been tagged as deprecated with the
    is_deprecated() method.
    :param flag: The flag being invoked, e.g. --foo
    """
    flag = flag.split('=')[0]
    deprecated_version, deprecated_hint = self._deprecated_flags[flag]
    scope = self._scope or 'DEFAULT'
    message = 'Option {flag} in scope {scope} is deprecated and will be removed in version ' \
              '{removal_version}'.format(flag=flag, scope=scope,
                                         removal_version=deprecated_version)
    hint = deprecated_hint or ''
    return '{}. {}'.format(message, hint)

  def deprecated_check(self, flags):
    """Emit a warning message if one of these flags is marked as deprecated.

    :param flags: list of string flags to check.  e.g. [ '--foo', '--no-bar', ... ]
    """
    for flag in flags:
      if self.is_deprecated(flag):
        warnings.warn('*** {}'.format(self.deprecated_message(flag)), DeprecationWarning,
                      stacklevel=9999) # out of range stacklevel to suppress printing source line.

  def _register(self, dest, args, kwargs, recursive):
    """Recursively register the option for parsing."""
    ranked_default = self._compute_default(dest, is_invertible=False, kwargs=kwargs)
    kwargs_with_default = dict(kwargs, default=ranked_default)
    self._argparser.add_argument(*args, **kwargs_with_default)

    if recursive:
      # Propagate registration down to inner scopes.
      for child_parser in self._child_parsers:
        child_parser._register(dest, args, kwargs, recursive)

  def _register_boolean(self, dest, args, kwargs, inverse_args, inverse_kwargs, recursive):
    """Recursively register the boolean option, and its inverse, for parsing."""
    group = self._argparser.add_mutually_exclusive_group()
    ranked_default = self._compute_default(dest, is_invertible=True, kwargs=kwargs)
    kwargs_with_default = dict(kwargs, default=ranked_default)
    group.add_argument(*args, **kwargs_with_default)
    group.add_argument(*inverse_args, **inverse_kwargs)

    if recursive:
      # Propagate registration down to inner scopes.
      for child_parser in self._child_parsers:
        child_parser._register_boolean(dest, args, kwargs, inverse_args, inverse_kwargs, recursive)

  def _validate(self, args, kwargs):
    """Ensure that the caller isn't trying to use unsupported argparse features."""
    for arg in args:
      if not arg.startswith('-'):
        raise RegistrationError('Option {0} in scope {1} must begin '
                                'with a dash.'.format(arg, self._scope))
      if not arg.startswith('--') and len(arg) > 2:
        raise RegistrationError('Multicharacter option {0} in scope {1} must begin '
                                'with a double-dash'.format(arg, self._scope))
    if 'nargs' in kwargs and kwargs['nargs'] != '?':
      raise RegistrationError('nargs={0} unsupported in registration of option {1} in '
                              'scope {2}.'.format(kwargs['nargs'], args, self._scope))
    if 'required' in kwargs:
      raise RegistrationError('required unsupported in registration of option {0} in '
                              'scope {1}.'.format(args, self._scope))

  def _set_dest(self, args, kwargs):
    """Maps the externally-used dest to a scoped one only seen internally.

    If an option is re-registered in an inner scope, it'll shadow the external dest but will
    use a different internal one. This is important in the case that an option is registered
    with two names (say -x, --xlong) and we only re-register one of them, say --xlong, in an
    inner scope. In this case we no longer want them to write to the same dest, so we can
    use both (now with different meanings) in the inner scope.

    Note: Modfies kwargs.
    """
    dest = self._select_dest(args, kwargs)
    scoped_dest = '_{0}_{1}__'.format(self._scope or 'DEFAULT', dest)

    # Make argparse write to the internal dest.
    kwargs['dest'] = scoped_dest

    # Make reads from the external dest forward to the internal one.
    self._dest_forwardings[dest] = scoped_dest

    # Also forward all option aliases, so we can reference -x (as options.x) in the example above.
    for arg in args:
      self._dest_forwardings[arg.lstrip('-').replace('-', '_')] = scoped_dest
    return dest

  def _select_dest(self, args, kwargs):
    """Select the dest name for the option.

    Replicated from the dest inference logic in argparse:
    '--foo-bar' -> 'foo_bar' and '-x' -> 'x'.
    """
    dest = kwargs.get('dest')
    if dest:
      return dest
    arg = next((a for a in args if a.startswith('--')), args[0])
    return arg.lstrip('-').replace('-', '_')

  def _compute_default(self, dest, is_invertible, kwargs):
    """Compute the default value to use for an option's registration.

    The source of the default value is chosen according to the ranking in RankedValue.
    """
    config_section = 'DEFAULT' if self._scope == GLOBAL_SCOPE else self._scope
    udest = dest.upper()
    if self._scope == GLOBAL_SCOPE:
      # For convenience, we allow three forms of env var for global scope options.
      # The fully-specified env var is PANTS_DEFAULT_FOO, which is uniform with PANTS_<SCOPE>_FOO
      # for all the other scopes.  However we also allow simply PANTS_FOO. And if the option name
      # itself starts with 'pants-' then we also allow simply FOO. E.g., PANTS_WORKDIR instead of
      # PANTS_PANTS_WORKDIR or PANTS_DEFAULT_PANTS_WORKDIR. We take the first specified value we
      # find, in this order: PANTS_DEFAULT_FOO, PANTS_FOO, FOO.
      env_vars = ['PANTS_DEFAULT_{0}'.format(udest), 'PANTS_{0}'.format(udest)]
      if udest.startswith('PANTS_'):
        env_vars.append(udest)
    else:
      env_vars = ['PANTS_{0}_{1}'.format(config_section.upper().replace('.', '_'), udest)]
    value_type = self.str_to_bool if is_invertible else kwargs.get('type', str)
    env_val_str = None
    if self._env:
      for env_var in env_vars:
        if env_var in self._env:
          env_val_str = self._env.get(env_var)
          break
    env_val = None if env_val_str is None else value_type(env_val_str)
    if kwargs.get('action') == 'append':
      config_val_strs = self._config.getlist(config_section, dest) if self._config else None
      config_val = (None if config_val_strs is None else
                    [value_type(config_val_str) for config_val_str in config_val_strs])
      default = []
    else:
      config_val_str = (self._config.get(config_section, dest, default=None)
                        if self._config else None)
      config_val = None if config_val_str is None else value_type(config_val_str)
      default = None
    hardcoded_val = kwargs.get('default')
    return RankedValue.choose(None, env_val, config_val, hardcoded_val, default)

  def _create_inverse_kwargs(self, kwargs):
    """Create the kwargs for registering the inverse of a boolean flag."""
    inverse_kwargs = copy.copy(kwargs)
    inverse_action = 'store_true' if kwargs.get('action') == 'store_false' else 'store_false'
    inverse_kwargs['action'] = inverse_action
    inverse_kwargs.pop('default', None)
    return inverse_kwargs

  def _register_child_parser(self, child):
    self._child_parsers.append(child)

  def _freeze(self):
    self._frozen = True

  def __str__(self):
    return 'Parser({})'.format(self._scope)
