# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import os
import re
import warnings
from argparse import ArgumentParser

import six

from pants.base.deprecated import check_deprecated_semver
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.custom_types import list_option
from pants.option.errors import ParseError, RegistrationError
from pants.option.option_util import is_boolean_flag
from pants.option.ranked_value import RankedValue
from pants.option.scope import ScopeInfo
from pants.util.memo import memoized_property


# Standard ArgumentParser prints usage and exits on error. We subclass so we can raise instead.
# Note that subclassing ArgumentParser for this purpose is allowed by the argparse API.
class CustomArgumentParser(ArgumentParser):

  def __init__(self, scope, *args, **kwargs):
    super(CustomArgumentParser, self).__init__(*args, **kwargs)
    self._scope = scope

  def error(self, message):
    scope = 'global' if self._scope == GLOBAL_SCOPE else self._scope
    raise ParseError('{0} in {1} scope'.format(message, scope))


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

    # All option args registered with this parser.  Used to prevent shadowing args in inner scopes.
    self._known_args = set()

    # List of (args, kwargs) registration pairs, exactly as captured at registration time.
    # Note that:
    # 1. kwargs may include our custom, non-argparse arguments (e.g., 'recursive' and 'advanced').
    # 2. kwargs will include a value for 'default', computed from env vars, pants.ini and the
    #    static 'default' in the originally passed-in kwargs (if any).
    self._option_registrations = []

    # Names of args that have already been registered with argparse.  Used to prevent
    # double-registration (e.g., during bootstrapping).
    self._argparse_registered_args = set()

    # Map of dest -> (deprecated_version, deprecated_hint), for deprecated options.
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

  def parse_args(self, flags, namespace):
    """Set values for this parser's options on the namespace object."""
    for args, kwargs in self.option_registrations_iter():
      self._argparse_register(args, kwargs)
    new_args = vars(self._argparser.parse_args(flags))
    namespace.update(new_args)

    # Check for deprecated flags.
    for key in self._deprecated_option_dests.keys():
      if namespace.get_rank(key) == RankedValue.FLAG:
        warnings.warn('*** {}'.format(self._deprecated_message(key)), DeprecationWarning,
                      stacklevel=9999)  # Out of range stacklevel to suppress printing src line.
    return namespace

  def option_registrations_iter(self):
    """Returns an iterator over the normalized registration arguments of each option in this parser.

    Each yielded item is an (args, kwargs) pair, as passed to register(), except that kwargs
    will be normalized in the following ways:

      - It will always have 'dest' explicitly set.
      - It will always have 'default' explicitly set, and the value will be a RankedValue.
      - For recursive options, the original registrar will also have 'recursive_root' set.

    Note that recursive options we inherit from a parent will also be yielded here, with
    the correctly-scoped default value.
    """
    def normalize_kwargs(orig_kwargs):
      nkwargs = copy.copy(orig_kwargs)
      if 'dest' not in nkwargs:
        nkwargs['dest'] = self._select_dest(args)
      if not ('default' in nkwargs and isinstance(nkwargs['default'], RankedValue)):
        nkwargs['default'] = self._compute_default(nkwargs)  # Requires dest to be set.
      return nkwargs

    # First yield any recursive options we inherit from our parent.
    if self._parent_parser:
      for args, kwargs in self._parent_parser._recursive_option_registration_args():
        yield args, normalize_kwargs(kwargs)

    # Then yield our directly-registered options.
    # This must come after yielding inherited recursive options, so we can detect shadowing.
    for args, kwargs in self._option_registrations:
      normalized_kwargs = normalize_kwargs(kwargs)
      if 'recursive' in normalized_kwargs:
        if self._scope_info.category == ScopeInfo.SUBSYSTEM:
          raise RegistrationError("Subsystem option {} in scope {} sets 'recursive'. Subsystem "
                                  "options are always recursive.".format(args[0], self.scope))
        # If we're the original registrar, make sure we can distinguish that.
        normalized_kwargs['recursive_root'] = True
      yield args, normalized_kwargs

  def _recursive_option_registration_args(self):
    """Yield args, kwargs pairs for just our recursive options.

    Includes all the options we inherit recursively from our ancestors.
    """
    if self._parent_parser:
      for args, kwargs in self._parent_parser._recursive_option_registration_args():
        yield args, kwargs
    for args, kwargs in self._option_registrations:
      # Note that all subsystem options are implicitly recursive: a subscope of a subsystem
      # scope is another (optionable-specific) instance of the same subsystem, so it needs
      # all the same options.
      if self._scope_info.category == ScopeInfo.SUBSYSTEM or 'recursive' in kwargs:
        yield args, kwargs

  def register(self, *args, **kwargs):
    """Register an option, using argparse params.

    Note that we don't actually do the argparse registration yet. That's done lazily.

    Custom extensions to argparse params:
    :param advanced: If True, the option will be suppressed when displaying help.
    :param recursive: If True, the option will be registered on all subscopes as well.
    :param fingerprint: If True, this option is mixed into fingerprints generated by tasks
                        that use it.
    :param fromfile: If True, this option supports the --foo=@filepath notation, in which the
                     option value is read from the file.
    :param deprecated_version: Mark an option as deprecated.  The value is a semver that indicates
       the release at which the option should be removed from the code.
    :param deprecated_hint: A message to display to the user when displaying help for or invoking
       a deprecated option.
    """
    if self._frozen:
      raise RegistrationError('Cannot register option {} in scope {} after registering options '
                              'in any of its inner scopes.'.format(args[0], self._scope))

    # Prevent further registration in enclosing scopes.
    ancestor = self._parent_parser
    while ancestor:
      ancestor._freeze()
      ancestor = ancestor._parent_parser

    # Record the args. We'll do the underlying argparse registration on-demand.
    self._option_registrations.append((args, kwargs))
    if self._parent_parser:
      for arg in args:
        existing_scope = self._parent_parser._existing_scope(arg)
        if existing_scope is not None:
          raise RegistrationError('Option {} in scope {} already registered in {}'.format(
            arg, self.scope, _scope_str(existing_scope)))
    self._known_args.update(args)

  @memoized_property
  def _argparser(self):
    return CustomArgumentParser(scope=self._scope, conflict_handler='resolve')

  def _argparse_register(self, args, kwargs):
    """Do the deferred argparse registration."""
    # This check prevents repeat registration of the same option, e.g., during bootstrapping,
    # when we parse some global options multiple times.
    if args[0] not in self._argparse_registered_args:
      self._validate(args, kwargs)
      argparse_kwargs = self._clean_argparse_kwargs(kwargs)
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
    self._argparse_registered_args.update(args)

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

  _custom_kwargs = ('advanced', 'recursive', 'recursive_root', 'registering_class',
                    'fingerprint', 'deprecated_version', 'deprecated_hint', 'fromfile')

  def _clean_argparse_kwargs(self, kwargs):
    deprecated_version = kwargs.get('deprecated_version', None)
    deprecated_hint = kwargs.get('deprecated_hint', '')

    if deprecated_version is not None:
      check_deprecated_semver(deprecated_version)
      self._deprecated_option_dests[kwargs['dest']] = (deprecated_version, deprecated_hint)

    # For argparse registration, remove our custom kwargs.
    argparse_kwargs = dict(kwargs)
    for custom_kwarg in self._custom_kwargs:
      argparse_kwargs.pop(custom_kwarg, None)
    return argparse_kwargs

  def _validate(self, args, kwargs):
    """Ensure that the caller isn't trying to use unsupported argparse features."""
    scope_str = _scope_str(self.scope)
    if not args:
      raise RegistrationError('No args provided for option in {}'.format(scope_str))
    for arg in args:
      if not arg.startswith('-'):
        raise RegistrationError('Option {} in {} must begin '
                                'with a dash.'.format(arg, scope_str))
      if not arg.startswith('--') and len(arg) > 2:
        raise RegistrationError('Multicharacter option {} in {} must begin '
                                'with a double-dash'.format(arg, scope_str))
    if 'nargs' in kwargs and kwargs['nargs'] != '?':
      raise RegistrationError('nargs={} unsupported in registration of option {} in '
                              '{}.'.format(kwargs['nargs'], args, scope_str))
    if 'required' in kwargs:
      raise RegistrationError('required unsupported in registration of option {} in '
                              '{}.'.format(args, scope_str))

  def _existing_scope(self, arg):
    if arg in self._known_args:
      return self._scope
    elif self._parent_parser:
      return self._parent_parser._existing_scope(arg)
    else:
      return None

  _ENV_SANITIZER_RE = re.compile(r'[.-]')

  def _select_dest(self, args):
    """Select the dest name for the option.

    Replicated from the dest inference logic in argparse:
    '--foo-bar' -> 'foo_bar' and '-x' -> 'x'.
    """
    arg = next((a for a in args if a.startswith('--')), args[0])
    return arg.lstrip('-').replace('-', '_')

  def _compute_default(self, kwargs):
    """Compute the default value to use for an option's registration.

    The source of the default value is chosen according to the ranking in RankedValue.

    Note: Only call if kwargs has a 'dest' key set.
    """
    dest = kwargs['dest']
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


def _scope_str(scope):
  return 'global scope' if scope == GLOBAL_SCOPE else "scope '{}'".format(scope)
