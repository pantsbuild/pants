# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from argparse import ArgumentParser, _HelpAction
import copy

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.errors import ParseError, RegistrationError
from pants.option.help_formatter import PantsHelpFormatter
from pants.option.ranked_value import RankedValue


# Standard ArgumentParser prints usage and exits on error. We subclass so we can raise instead.
# Note that subclassing ArgumentParser for this purpose is allowed by the argparse API.
class CustomArgumentParser(ArgumentParser):
  def error(self, message):
    raise ParseError(message)

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
  def __init__(self, env, config, scope, parent_parser):
    self._env = env
    self._config = config
    self._scope = scope

    # If True, no more registration is allowed on this parser.
    self._frozen = False

    # The argparser we use for actually parsing args.
    self._argparser = CustomArgumentParser(conflict_handler='resolve')

    # The argparser we use for formatting help messages.
    # We don't use self._argparser for this as it will have all options from enclosing scopes
    # registered on it too, which would create unnecessarily repetitive help messages.
    self._help_argparser = CustomArgumentParser(conflict_handler='resolve',
                                                formatter_class=PantsHelpFormatter)

    # If True, we have at least one option to show help for.
    self._has_help_options = False

    # Map of external to internal dest names. See docstring for _set_dest below.
    self._dest_forwardings = {}

    # A Parser instance, or None for the global scope parser.
    self._parent_parser = parent_parser

    # List of Parser instances.
    self._child_parsers = []

    if self._parent_parser:
      self._parent_parser._register_child_parser(self)

  def parse_args(self, args, namespace):
    """Parse the given args and set their values onto the namespace object's attributes."""
    namespace.add_forwardings(self._dest_forwardings)
    new_args = self._argparser.parse_args(args)
    namespace.update(vars(new_args))
    return namespace

  def format_help(self):
    """Return a help message for the options registered on this object."""
    return self._help_argparser.format_help() if self._has_help_options else ''

  def register(self, *args, **kwargs):
    """Register an option, using argparse params."""
    if self._frozen:
      raise RegistrationError('Cannot register option {0} in scope {1} after registering options '
                              'in any of its inner scopes.'.format(args[0], self._scope))

    # Prevent further registration in enclosing scopes.
    ancestor = self._parent_parser
    while ancestor:
      ancestor._freeze()
      ancestor = ancestor._parent_parser

    self._validate(args, kwargs)
    dest = self._set_dest(args, kwargs)

    # Is this a boolean flag?
    if kwargs.get('action') in ('store_false', 'store_true'):
      inverse_args = []
      help_args = []
      for flag in args:
        if flag.startswith('--') and not flag.startswith('--no-'):
          inverse_args.append('--no-' + flag[2:])
          help_args.append('--[no-]{0}'.format(flag[2:]))
        else:
          help_args.append(flag)
    else:
      inverse_args = None
      help_args = args

    # Register the option, only on this scope, for the purpose of displaying help.
    # Note that we'll only display the default value for this scope, even though the
    # default may be overridden in inner scopes.
    raw_default = self._compute_default(dest, kwargs).value
    kwargs_with_default = dict(kwargs, default=raw_default)
    self._help_argparser.add_argument(*help_args, **kwargs_with_default)
    self._has_help_options = True

    # Register the option for the purpose of parsing, on this and all enclosed scopes.
    if inverse_args:
      inverse_kwargs = self._create_inverse_kwargs(kwargs)
      self._register_boolean(dest, args, kwargs, inverse_args, inverse_kwargs)
    else:
      self._register(dest, args, kwargs)

  def _register(self, dest, args, kwargs):
    """Recursively register the option for parsing."""
    ranked_default = self._compute_default(dest, kwargs)
    kwargs_with_default = dict(kwargs, default=ranked_default)
    self._argparser.add_argument(*args, **kwargs_with_default)

    # Propagate registration down to inner scopes.
    for child_parser in self._child_parsers:
      child_parser._register(dest, args, kwargs)

  def _register_boolean(self, dest, args, kwargs, inverse_args, inverse_kwargs):
    """Recursively register the boolean option, and its inverse, for parsing."""
    group = self._argparser.add_mutually_exclusive_group()
    ranked_default = self._compute_default(dest, kwargs)
    kwargs_with_default = dict(kwargs, default=ranked_default)
    group.add_argument(*args, **kwargs_with_default)
    group.add_argument(*inverse_args, **inverse_kwargs)

    # Propagate registration down to inner scopes.
    for child_parser in self._child_parsers:
      child_parser._register_boolean(dest, args, kwargs, inverse_args, inverse_kwargs)

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
      raise RegistrationError('{0} unsupported in registration of option {1} in '
                              'scope {2}.'.format(k, args, self._scope))

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

  def _compute_default(self, dest, kwargs):
    """Compute the default value to use for an option's registration.

    The source of the default value is chosen according to the ranking in RankedValue.
    """
    config_section = 'DEFAULT' if self._scope == GLOBAL_SCOPE else self._scope
    env_var = 'PANTS_{0}_{1}'.format(config_section.upper().replace('.', '_'), dest.upper())
    value_type = kwargs.get('type', str)
    env_val_str = self._env.get(env_var) if self._env else None

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
    return 'Parser(%s)' % self._scope
