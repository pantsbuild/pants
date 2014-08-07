# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from argparse import ArgumentParser
import copy

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.help_formatter import PantsHelpFormatter
from pants.option.legacy_options import LegacyOptions
from pants.option.ranked_value import RankedValue


class RegistrationError(Exception):
  """An error at option registration time."""
  pass


class ParseError(Exception):
  """An error at flag parsing time."""
  pass


# Standard ArgumentParser prints usage and exits on error. We subclass so we can raise instead.
# Note that subclassing ArgumentParser for this purpose is allowed by the argparse API.
class CustomArgumentParser(ArgumentParser):
  def error(self, message):
    raise ParseError(message)


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

  For migration purposes, this object also interacts with the legacy flags system:

  Recall that the old flags system uses optparse, and scopes the flags using a prefix, e.g.,
  ./pants --compile-scala-foo.

  Whereas  this new system uses argparse and scopes the flags using command-line context, e.g.,
  ./pants compile.scala --foo.

  When registering (scala.compile, --foo), this object can also register it as --scala-compile-foo
  on the old system.  This allows us to transition registration code to the new registration API
  while retaining the old flag names.

  Eventually all usages will switch to the new flag names, and we can remove this migration code.

  :param env: a dict of environment variables.
  :param config: data from a config file (must support config.get(section, name, default=)).
  :param scope: the scope this parser acts for.
  :param parent_parser: the parser for the scope immediately enclosing this one, or
         None if this is the global scope.
  :param legacy_parser: an optparse.OptionParser instance for handling legacy options.
  """
  def __init__(self, env, config, scope, parent_parser, legacy_parser=None):
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

    # Handles legacy options on our behalf.
    self._legacy_options = LegacyOptions(scope, legacy_parser) if legacy_parser else None

  def parse_args(self, args, namespace):
    """Parse the given args and set their values onto the namespace object's attributes."""
    namespace.add_forwardings(self._dest_forwardings)
    new_args = self._argparser.parse_args(args)
    namespace.update(vars(new_args))
    return namespace

  def format_help(self, legacy=False):
    """Return a help message for the options registered on this object."""
    if legacy:
      return self._legacy_options.format_help()
    else:
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

    clean_kwargs = copy.copy(kwargs)  # Copy kwargs so we can remove legacy-related keys.
    kwargs = None  # Ensure no code below modifies kwargs accidentally.
    self._validate(args, clean_kwargs)
    legacy_dest = clean_kwargs.pop('legacy', None)
    dest = self._set_dest(args, clean_kwargs, legacy_dest)

    # Is this a boolean flag?
    if clean_kwargs.get('action') in ('store_false', 'store_true'):
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

    # Register the option for displaying help.
    # Note that we'll only display the default value for the scope in which
    # we registered, even though the default may be overridden in inner scopes.
    raw_default = self._compute_default(dest, clean_kwargs).value
    clean_kwargs_with_default = dict(clean_kwargs, default=raw_default)
    self._help_argparser.add_argument(*help_args, **clean_kwargs_with_default)
    self._has_help_options = True

    # Also register the option as a legacy option, if needed.
    if self._legacy_options and legacy_dest:
      self._legacy_options.register(args, clean_kwargs_with_default, legacy_dest)

    # Register the option for parsing, on this and all enclosed scopes.
    if inverse_args:
      inverse_kwargs = self._create_inverse_kwargs(clean_kwargs)
      if self._legacy_options:
        self._legacy_options.register(inverse_args, inverse_kwargs, legacy_dest)
      self._register_boolean(dest, args, clean_kwargs, inverse_args, inverse_kwargs)
    else:
      self._register(dest, args, clean_kwargs)

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
    for k in ['nargs', 'required']:
      if k in kwargs:
        raise RegistrationError('%s unsupported in registration of option %s.' % (k, args))

  def _set_dest(self, args, kwargs, legacy_dest):
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

    # Forward another hop, to the legacy flag.  Note that this means that *only* the
    # legacy flag is supported for now.  This will be removed after we're finished migrating
    # option registration to the new system, and work on migrating the actual runtime
    # command-line parsing.
    if legacy_dest:
      self._dest_forwardings[scoped_dest] = legacy_dest
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
    config_val = self._config.get(config_section, dest, default=None) if self._config else None
    hardcoded_val = kwargs.get('default')
    return RankedValue.choose(None, env_val, config_val, hardcoded_val)

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
