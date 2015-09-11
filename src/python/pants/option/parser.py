# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import os
import re
import warnings
from argparse import ArgumentParser, _HelpAction
from collections import defaultdict

import six

from pants.base.deprecated import check_deprecated_semver
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.custom_types import list_option
from pants.option.errors import ParseError, RegistrationError
from pants.option.option_util import is_boolean_flag
from pants.option.ranked_value import RankedValue
from pants.option.scope import ScopeInfo


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
  """

  class BooleanConversionError(ParseError):
    """Indicates a value other than 'True' or 'False' when attempting to parse a bool."""

  class FromfileError(ParseError):
    """Indicates a problem reading a value @fromfile."""

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

  def __init__(self, env, config, scope_info, parent_parser, option_tracker):
    """Create a Parser instance.

    :param env: a dict of environment variables.
    :param config: data from a config file (must support config.get[list](section, name, default=)).
    :param scope_info: the scope this parser acts for.
    :param parent_parser: the parser for the scope immediately enclosing this one, or
                          None if this is the global scope.
    :param option_tracker: the option tracker to record where option values came from.
    """
    self._env = env
    self._config = config
    self._scope_info = scope_info
    self._scope = self._scope_info.scope
    self._option_tracker = option_tracker

    # If True, no more registration is allowed on this parser.
    self._frozen = False

    # List of (args, kwargs) registration pairs, more-or-less as captured at registration time.
    # Note that:
    # 1. kwargs may include our custom, non-argparse arguments (e.g., 'recursive' and 'advanced').
    # 2. kwargs will include a value for 'default', computed from env vars, pants.ini and the
    #    static 'default' in the originally passed-in kwargs (if any).
    # 3. args will only contain names that have not been shadowed by a subsequent registration.
    #    For example, if an outer scope registers [-x, --xlong] on an inner scope (via recursion)
    #    and then the inner scope re-registers [--xlong], the args for the first registration
    #    here will contain only [-x].
    self._registration_args = []

    # arg -> list that arg appears in, in self_registration_args above.
    # Used to ensure that shadowed args are removed from their lists.
    self._arg_lists_by_arg = {}

    # The argparser we use for actually parsing args.
    self._argparser = CustomArgumentParser(scope=self._scope, conflict_handler='resolve')

    # Map of external to internal dest names. See docstring for _set_dest below.
    self._dest_forwardings = {}

    # Map of dest -> (deprecated_version, deprecated_hint), for deprecated options.
    # The keys are external dest names (the ones seen by the user, not by argparse).
    self._deprecated_option_dests = {}

    # A Parser instance, or None for the global scope parser.
    self._parent_parser = parent_parser

    # List of Parser instances.
    self._child_parsers = []

    if self._parent_parser:
      self._parent_parser._register_child_parser(self)

  @property
  def scope(self):
    return self._scope

  def walk(self, callback):
    """Invoke callback on this parser and its descendants, in depth-first order."""
    callback(self)
    for child in self._child_parsers:
      child.walk(callback)

  def parse_args(self, args, namespace):
    """Parse the given args and set their values onto the namespace object's attributes."""
    namespace.add_forwardings(self._dest_forwardings)
    new_args = vars(self._argparser.parse_args(args))
    namespace.update(new_args)
    # Compute the inverse of the dest forwardings.
    # We do this here and not when creating the forwardings, because forwardings inherited
    # from outer scopes can be overridden in inner scopes, so this computation is only
    # correct after all options have been registered on all scopes.
    inverse_dest_forwardings = defaultdict(set)
    for src, dest in self._dest_forwardings.items():
      inverse_dest_forwardings[dest].add(src)

    # Check for deprecated flags.
    all_deprecated_dests = set(self._deprecated_option_dests.keys())
    for internal_dest in new_args.keys():
      external_dests = inverse_dest_forwardings.get(internal_dest, set())
      deprecated_dests = all_deprecated_dests & external_dests
      if deprecated_dests:
        # Check all dests. Typically there is only one, unless the option was registered with
        # multiple aliases (which we almost never do).  And in any case we'll only warn for the
        # ones actually used on the cmd line.
        for dest in deprecated_dests:
          if namespace.get_rank(dest) == RankedValue.FLAG:
            warnings.warn('*** {}'.format(self._deprecated_message(dest)), DeprecationWarning,
                          stacklevel=9999)  # Out of range stacklevel to suppress printing src line.
    return namespace

  @property
  def registration_args(self):
    """Returns the registration args, in registration order.

    :return: A list of (args, kwargs) pairs.
    """
    return self._registration_args

  def registration_args_iter(self):
    """Returns an iterator over the registration arguments of each option in this parser.

    Each yielded item is a (dest, args, kwargs) triple.  `dest` is the canonical name that can be
    used to retrieve the option value, if the option has multiple names.
    See comment on self._registration_args above for caveats re (args, kwargs).

    For consistency, items are iterated over in lexicographical order, not registration order.
    """
    for args, kwargs in sorted(self._registration_args):
      if args:  # Otherwise all args have been shadowed, so ignore.
        dest = self._select_dest(args)
        yield dest, args, kwargs

  def register(self, *args, **kwargs):
    """Register an option, using argparse params.

    Custom extensions to argparse params:
    :param advanced: if True, the option will be suppressed when displaying help.
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

    self._validate(args, kwargs)
    dest = self._set_dest(args, kwargs)
    if 'recursive' in kwargs:
      if self._scope_info.category == ScopeInfo.SUBSYSTEM:
        raise ParseError('Option {} in scope {} registered as recursive, but subsystem options '
                         'may not set recursive=True.'.format(args[0], self.scope))
      kwargs['recursive_root'] = True  # So we can distinguish the original registrar.
    if self._scope_info.category == ScopeInfo.SUBSYSTEM:
      kwargs['subsystem'] = True
    self._register(dest, args, kwargs)  # Note: May modify kwargs (to remove recursive_root).

  def _deprecated_message(self, dest):
    """Returns the message to be displayed when a deprecated option is specified on the cmd line.

    Assumes that the option is indeed deprecated.

    :param dest: The dest of the option being invoked.
    """
    deprecated_version, deprecated_hint = self._deprecated_option_dests[dest]
    scope = self._scope or 'DEFAULT'
    message = 'Option {dest} in scope {scope} is deprecated and will be removed in version ' \
              '{removal_version}'.format(dest=dest, scope=scope,
                                         removal_version=deprecated_version)
    hint = deprecated_hint or ''
    return '{}. {}'.format(message, hint)

  _custom_kwargs = ('advanced', 'recursive', 'recursive_root', 'subsystem', 'registering_class',
                    'fingerprint', 'deprecated_version', 'deprecated_hint', 'fromfile')

  def _clean_argparse_kwargs(self, dest, args, kwargs):
    ranked_default = self._compute_default(dest, kwargs=kwargs)
    kwargs_with_default = dict(kwargs, default=ranked_default)

    args_copy = list(args)
    for arg in args_copy:
      shadowed_arg_list = self._arg_lists_by_arg.get(arg)
      if shadowed_arg_list is not None:
        shadowed_arg_list.remove(arg)
      self._arg_lists_by_arg[arg] = args_copy
    self._registration_args.append((args_copy, kwargs_with_default))

    deprecated_version = kwargs.get('deprecated_version', None)
    deprecated_hint = kwargs.get('deprecated_hint', '')

    if deprecated_version is not None:
      check_deprecated_semver(deprecated_version)
      self._deprecated_option_dests[dest] = (deprecated_version, deprecated_hint)

    # For argparse registration, remove our custom kwargs.
    argparse_kwargs = dict(kwargs_with_default)
    for custom_kwarg in self._custom_kwargs:
      argparse_kwargs.pop(custom_kwarg, None)
    return argparse_kwargs

  def _register(self, dest, args, kwargs):
    """Register the option for parsing (recursively if needed)."""
    argparse_kwargs = self._clean_argparse_kwargs(dest, args, kwargs)
    if is_boolean_flag(argparse_kwargs):
      inverse_args = self._create_inverse_args(args)
      if inverse_args:
        inverse_argparse_kwargs = self._create_inverse_kwargs(argparse_kwargs)
        group = self._argparser.add_mutually_exclusive_group()
        group.add_argument(*args, **argparse_kwargs)
        group.add_argument(*inverse_args, **inverse_argparse_kwargs)
      else:
        self._argparser.add_argument(*args, **argparse_kwargs)
    else:
      self._argparser.add_argument(*args, **argparse_kwargs)

    if kwargs.get('recursive', False) or kwargs.get('subsystem', False):
      # Propagate registration down to inner scopes.
      for child_parser in self._child_parsers:
        kwargs.pop('recursive_root', False)
        child_parser._register(dest, args, kwargs)

  def _validate(self, args, kwargs):
    """Ensure that the caller isn't trying to use unsupported argparse features."""
    if not args:
      raise RegistrationError('No args provided for option in scope {}'.format(self.scope))
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
    dest = kwargs.get('dest') or self._select_dest(args)
    scoped_dest = '_{0}_{1}__'.format(self._scope or 'DEFAULT', dest)

    # Make argparse write to the internal dest.
    kwargs['dest'] = scoped_dest

    # Make reads from the external dest forward to the internal one.
    self._dest_forwardings[dest] = scoped_dest

    # Also forward all option aliases, so we can reference -x (as options.x) in the example above.
    for arg in args:
      self._dest_forwardings[arg.lstrip('-').replace('-', '_')] = scoped_dest
    return dest

  _ENV_SANITIZER_RE = re.compile(r'[.-]')

  def _select_dest(self, args):
    """Select the dest name for the option.

    Replicated from the dest inference logic in argparse:
    '--foo-bar' -> 'foo_bar' and '-x' -> 'x'.
    """
    arg = next((a for a in args if a.startswith('--')), args[0])
    return arg.lstrip('-').replace('-', '_')

  def _compute_default(self, dest, kwargs):
    """Compute the default value to use for an option's registration.

    The source of the default value is chosen according to the ranking in RankedValue.
    """
    is_fromfile = kwargs.get('fromfile', False)
    action = kwargs.get('action')
    if is_fromfile and action and action != 'append':
      raise ParseError('Cannot fromfile {} with an action ({}) in scope {}'
                       .format(dest, action, self._scope))

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
      sanitized_env_var_scope = self._ENV_SANITIZER_RE.sub('_', config_section.upper())
      env_vars = ['PANTS_{0}_{1}'.format(sanitized_env_var_scope, udest)]

    value_type = self.str_to_bool if is_boolean_flag(kwargs) else kwargs.get('type', str)

    env_val_str = None
    if self._env:
      for env_var in env_vars:
        if env_var in self._env:
          env_val_str = self._env.get(env_var)
          break

    config_val_str = self._config.get(config_section, dest, default=None)
    config_source_file = self._config.get_source_for_option(config_section, dest)
    if config_source_file is not None:
      config_source_file = os.path.relpath(config_source_file)

    def expand(val_str):
      if is_fromfile and val_str and val_str.startswith('@') and not val_str.startswith('@@'):
        fromfile = val_str[1:]
        try:
          with open(fromfile) as fp:
            return fp.read().strip()
        except IOError as e:
          raise self.FromfileError('Failed to read {} from file {}: {}'.format(dest, fromfile, e))
      else:
        # Support a literal @ for fromfile values via @@.
        return val_str[1:] if is_fromfile and val_str.startswith('@@') else val_str

    def parse_typed_list(val_str):
      return None if val_str is None else [value_type(x) for x in list_option(expand(val_str))]

    def parse_typed_item(val_str):
      return None if val_str is None else value_type(expand(val_str))

    # Handle the forthcoming conversions argparse will need to do by placing our parse hook - we
    # handle the conversions for env and config ourselves below.  Unlike the env and config
    # handling, `action='append'` does not need to be handled specially since appended flag values
    # come as single items' thus only `parse_typed_item` is ever needed for the flag value type
    # conversions.
    if is_fromfile:
      kwargs['type'] = parse_typed_item

    default, parse = ([], parse_typed_list) if action == 'append' else (None, parse_typed_item)
    config_val = parse(config_val_str)
    env_val = parse(env_val_str)
    hardcoded_val = kwargs.get('default')

    config_details = 'in {}'.format(config_source_file) if config_source_file else None

    choices = list(RankedValue.prioritized_iter(None, env_val, config_val, hardcoded_val, default))
    for choice in reversed(choices):
      details = config_details if choice.rank == RankedValue.CONFIG else None
      self._option_tracker.record_option(scope=self._scope, option=dest, value=choice.value,
                                         rank=choice.rank, details=details)

    return choices[0]

  def _create_inverse_args(self, args):
    inverse_args = []
    for arg in args:
      if arg.startswith('--'):
        if arg.startswith('--no-'):
          raise RegistrationError(
            'Invalid option name "{}". Boolean options names cannot start with --no-'.format(arg))
        inverse_args.append('--no-{}'.format(arg[2:]))
    return inverse_args

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
