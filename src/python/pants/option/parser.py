# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import copy
import json
import os
import re
import traceback
from collections import defaultdict

import Levenshtein
import yaml

from pants.base.deprecated import validate_deprecation_semver, warn_or_error
from pants.option.arg_splitter import GLOBAL_SCOPE, GLOBAL_SCOPE_CONFIG_SECTION
from pants.option.config import Config
from pants.option.custom_types import (DictValueComponent, ListValueComponent, UnsetBool,
                                       dict_option, dir_option, file_option, list_option,
                                       target_option)
from pants.option.errors import (BooleanOptionNameWithNo, FrozenRegistration, ImplicitValIsNone,
                                 InvalidKwarg, InvalidKwargNonGlobalScope, InvalidMemberType,
                                 MemberTypeNotAllowed, NoOptionNames, OptionAlreadyRegistered,
                                 OptionNameDash, OptionNameDoubleDash, ParseError,
                                 RecursiveSubsystemOption, Shadowing)
from pants.option.option_util import is_dict_option, is_list_option
from pants.option.ranked_value import RankedValue
from pants.option.scope import ScopeInfo
from pants.util.objects import SubclassesOf, datatype


class Parser:
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

  class MutuallyExclusiveOptionError(ParseError):
    """Raised when more than one option belonging to the same mutually exclusive group is specified."""

  @staticmethod
  def _ensure_bool(s):
    if isinstance(s, str):
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

  @classmethod
  def _invert(cls, s):
    if s is None:
      return None
    b = cls._ensure_bool(s)
    return not b

  def __init__(self, env, config, scope_info, parent_parser, option_tracker):
    """Create a Parser instance.

    :param env: a dict of environment variables.
    :param :class:`pants.option.config.Config` config: data from a config file.
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
    self._option_registrations = []

    # A Parser instance, or None for the global scope parser.
    self._parent_parser = parent_parser

    # List of Parser instances.
    self._child_parsers = []

    if self._parent_parser:
      self._parent_parser._register_child_parser(self)

  @property
  def scope(self):
    return self._scope

  @property
  def known_args(self):
    return self._known_args

  def walk(self, callback):
    """Invoke callback on this parser and its descendants, in depth-first order."""
    callback(self)
    for child in self._child_parsers:
      child.walk(callback)

  class ParseArgsRequest(datatype([
      ('flag_value_map', SubclassesOf(dict)),
      'namespace',
      'get_all_scoped_flag_names',
      ('levenshtein_max_distance', int),
  ])):

    @staticmethod
    def _create_flag_value_map(flags):
      """Returns a map of flag -> list of values, based on the given flag strings.

      None signals no value given (e.g., -x, --foo).
      The value is a list because the user may specify the same flag multiple times, and that's
      sometimes OK (e.g., when appending to list-valued options).
      """
      flag_value_map = defaultdict(list)
      for flag in flags:
        key, has_equals_sign, flag_val = flag.partition('=')
        if not has_equals_sign:
          if not flag.startswith('--'):  # '-xfoo' style.
            key = flag[0:2]
            flag_val = flag[2:]
          if not flag_val:
            # Either a short option with no value or a long option with no equals sign.
            # Important so we can distinguish between no value ('--foo') and setting to an empty
            # string ('--foo='), for options with an implicit_value.
            flag_val = None
        flag_value_map[key].append(flag_val)
      return flag_value_map

    def __new__(cls, flags_in_scope, namespace,
                get_all_scoped_flag_names,
                levenshtein_max_distance):
      """
      :param Iterable flags_in_scope: Iterable of arg strings to parse into flag values.
      :param namespace: The object to register the flag values on
      :param function get_all_scoped_flag_names: A 0-argument function which returns an iterable of
                                                 all registered option names in all their scopes. This
                                                 is used to create an error message with suggestions
                                                 when raising a `ParseError`.
      :param int levenshtein_max_distance: The maximum Levenshtein edit distance between option names
                                           to determine similarly named options when an option name
                                           hasn't been registered.
      """
      flag_value_map = cls._create_flag_value_map(flags_in_scope)
      return super(Parser.ParseArgsRequest, cls).__new__(cls, flag_value_map, namespace,
                                                         get_all_scoped_flag_names,
                                                         levenshtein_max_distance)

  def parse_args(self, parse_args_request):
    """Set values for this parser's options on the namespace object.

    :param Parser.ParseArgsRequest parse_args_request: parameters for parsing this parser's
                                                       arguments.
    :returns: The `parse_args_request.namespace` object that the option values are being registered
              on.
    :raises: :class:`ParseError` if any flags weren't recognized.
    """

    flag_value_map = parse_args_request.flag_value_map
    namespace = parse_args_request.namespace
    get_all_scoped_flag_names = parse_args_request.get_all_scoped_flag_names
    levenshtein_max_distance = parse_args_request.levenshtein_max_distance

    mutex_map = defaultdict(list)
    for args, kwargs in self._unnormalized_option_registrations_iter():
      self._validate(args, kwargs)
      dest = self.parse_dest(*args, **kwargs)

      # Compute the values provided on the command line for this option.  Note that there may be
      # multiple values, for any combination of the following reasons:
      #   - The user used the same flag multiple times.
      #   - The user specified a boolean flag (--foo) and its inverse (--no-foo).
      #   - The option has multiple names, and the user used more than one of them.
      #
      # We also check if the option is deprecated, but we only do so if the option is explicitly
      # specified as a command-line flag, so we don't spam users with deprecated option values
      # specified in config, which isn't something they control.
      implicit_value = kwargs.get('implicit_value')
      if implicit_value is None and kwargs.get('type') == bool:
        implicit_value = True  # Allows --foo to mean --foo=true.

      flag_vals = []

      def add_flag_val(v):
        if v is None:
          if implicit_value is None:
            raise ParseError('Missing value for command line flag {} in {}'.format(
              arg, self._scope_str()))
          else:
            flag_vals.append(implicit_value)
        else:
          flag_vals.append(v)

      for arg in args:
        # If the user specified --no-foo on the cmd line, treat it as if the user specified
        # --foo, but with the inverse value.
        if kwargs.get('type') == bool:
          inverse_arg = self._inverse_arg(arg)
          if inverse_arg in flag_value_map:
            flag_value_map[arg] = [self._invert(v) for v in flag_value_map[inverse_arg]]
            implicit_value = self._invert(implicit_value)
            del flag_value_map[inverse_arg]

        if arg in flag_value_map:
          for v in flag_value_map[arg]:
            add_flag_val(v)
          del flag_value_map[arg]

      # Get the value for this option, falling back to defaults as needed.
      try:
        val = self._compute_value(dest, kwargs, flag_vals)
      except ParseError as e:
        # Reraise a new exception with context on the option being processed at the time of error.
        # Note that other exception types can be raised here that are caught by ParseError (e.g.
        # BooleanConversionError), hence we reference the original exception type as type(e).
        raise type(e)(
          'Error computing value for {} in {} (may also be from PANTS_* environment variables).'
          '\nCaused by:\n{}'.format(', '.join(args), self._scope_str(), traceback.format_exc())
        )

      # If the option is explicitly given, check deprecation and mutual exclusion.
      if val.rank > RankedValue.HARDCODED:
        self._check_deprecated(dest, kwargs)

        mutex_dest = kwargs.get('mutually_exclusive_group')
        if mutex_dest:
          mutex_map[mutex_dest].append(dest)
          dest = mutex_dest
        else:
          mutex_map[dest].append(dest)

        if len(mutex_map[dest]) > 1:
          raise self.MutuallyExclusiveOptionError(
            "Can only provide one of the mutually exclusive options {}".format(mutex_map[dest]))

      setattr(namespace, dest, val)

    # See if there are any unconsumed flags remaining, and if so, raise a ParseError.
    if flag_value_map:
      self._raise_error_for_invalid_flag_names(
        flag_value_map,
        all_scoped_flag_names=list(get_all_scoped_flag_names()),
        levenshtein_max_distance=levenshtein_max_distance)

    return namespace

  def _raise_error_for_invalid_flag_names(self, flag_value_map, all_scoped_flag_names,
                                          levenshtein_max_distance):
    """Identify similar option names to unconsumed flags and raise a ParseError with those names."""
    matching_flags = {}
    for flag_name in flag_value_map.keys():
      # We will be matching option names without their leading hyphens, in order to capture both
      # short and long-form options.
      flag_normalized_unscoped_name = re.sub(r'^-+', '', flag_name)
      flag_normalized_scoped_name = (
        '{}-{}'.format(self.scope.replace('.', '-'), flag_normalized_unscoped_name)
        if self.scope != GLOBAL_SCOPE
        else flag_normalized_unscoped_name)

      substring_matching_option_names = []
      levenshtein_matching_option_names = defaultdict(list)
      for other_scoped_flag in all_scoped_flag_names:
        other_complete_flag_name = other_scoped_flag.scoped_arg
        other_normalized_scoped_name = other_scoped_flag.normalized_scoped_arg
        other_normalized_unscoped_name = other_scoped_flag.normalized_arg
        if flag_normalized_unscoped_name == other_normalized_unscoped_name:
          # If the unscoped option name itself matches, but the scope doesn't, display it.
          substring_matching_option_names.append(other_complete_flag_name)
        elif other_normalized_scoped_name.startswith(flag_normalized_scoped_name):
          # If the invalid scoped option name is the beginning of another scoped option name,
          # display it. This will also suggest long-form options such as --verbose for an attempted
          # -v (if -v isn't defined as an option).
          substring_matching_option_names.append(other_complete_flag_name)
        else:
          # If an unscoped option name is similar to the unscoped option from the command line
          # according to --option-name-check-distance, display the matching scoped option name. This
          # covers misspellings!
          unscoped_option_levenshtein_distance = Levenshtein.distance(flag_normalized_unscoped_name, other_normalized_unscoped_name)
          if unscoped_option_levenshtein_distance <= levenshtein_max_distance:
            # NB: We order the matched flags by Levenshtein distance compared to the entire option string!
            fully_scoped_levenshtein_distance = Levenshtein.distance(flag_normalized_scoped_name, other_normalized_scoped_name)
            levenshtein_matching_option_names[fully_scoped_levenshtein_distance].append(other_complete_flag_name)

      # If any option name matched or started with the invalid flag in any scope, put that
      # first. Then, display the option names matching in order of overall edit distance, in a deterministic way.
      all_matching_scoped_option_names = substring_matching_option_names + [
        flag
        for distance in sorted(levenshtein_matching_option_names.keys())
        for flag in sorted(levenshtein_matching_option_names[distance])
      ]
      if all_matching_scoped_option_names:
        matching_flags[flag_name] = all_matching_scoped_option_names

    if matching_flags:
      suggestions_message = ' Suggestions:\n{}'.format('\n'.join(
        '{}: [{}]'.format(flag_name, ', '.join(matches))
        for flag_name, matches in matching_flags.items()
      ))
    else:
      suggestions_message = ''
    raise ParseError(
      'Unrecognized command line flags on {scope}: {flags}.{suggestions_message}'
      .format(scope=self._scope_str(),
              flags=', '.join(flag_value_map.keys()),
              suggestions_message=suggestions_message))

  def option_registrations_iter(self):
    """Returns an iterator over the normalized registration arguments of each option in this parser.

    Useful for generating help and other documentation.

    Each yielded item is an (args, kwargs) pair, as passed to register(), except that kwargs
    will be normalized in the following ways:
      - It will always have 'dest' explicitly set.
      - It will always have 'default' explicitly set, and the value will be a RankedValue.
      - For recursive options, the original registrar will also have 'recursive_root' set.

    Note that recursive options we inherit from a parent will also be yielded here, with
    the correctly-scoped default value.
    """
    def normalize_kwargs(args, orig_kwargs):
      nkwargs = copy.copy(orig_kwargs)
      dest = self.parse_dest(*args, **nkwargs)
      nkwargs['dest'] = dest
      if not ('default' in nkwargs and isinstance(nkwargs['default'], RankedValue)):
        nkwargs['default'] = self._compute_value(dest, nkwargs, [])
      return nkwargs

    # First yield any recursive options we inherit from our parent.
    if self._parent_parser:
      for args, kwargs in self._parent_parser._recursive_option_registration_args():
        yield args, normalize_kwargs(args, kwargs)

    # Then yield our directly-registered options.
    # This must come after yielding inherited recursive options, so we can detect shadowing.
    for args, kwargs in self._option_registrations:
      normalized_kwargs = normalize_kwargs(args, kwargs)
      if 'recursive' in normalized_kwargs:
        # If we're the original registrar, make sure we can distinguish that.
        normalized_kwargs['recursive_root'] = True
      yield args, normalized_kwargs

  def _unnormalized_option_registrations_iter(self):
    """Returns an iterator over the raw registration arguments of each option in this parser.

    Each yielded item is an (args, kwargs) pair, exactly as passed to register(), except for
    substituting list and dict types with list_option/dict_option.

    Note that recursive options we inherit from a parent will also be yielded here.
    """
    # First yield any recursive options we inherit from our parent.
    if self._parent_parser:
      for args, kwargs in self._parent_parser._recursive_option_registration_args():
        yield args, kwargs
    # Then yield our directly-registered options.
    for args, kwargs in self._option_registrations:
      if 'recursive' in kwargs and self._scope_info.category == ScopeInfo.SUBSYSTEM:
        raise RecursiveSubsystemOption(self.scope, args[0])
      yield args, kwargs

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
    """Register an option."""
    if self._frozen:
      raise FrozenRegistration(self.scope, args[0])

    # Prevent further registration in enclosing scopes.
    ancestor = self._parent_parser
    while ancestor:
      ancestor._freeze()
      ancestor = ancestor._parent_parser

    if kwargs.get('type') == bool:
      default = kwargs.get('default')
      if default is None:
        # Unless a tri-state bool is explicitly opted into with the `UnsetBool` default value,
        # boolean options always have an implicit boolean-typed default. We make that default
        # explicit here.
        kwargs['default'] = not self._ensure_bool(kwargs.get('implicit_value', True))
      elif default is UnsetBool:
        kwargs['default'] = None

    # Record the args. We'll do the underlying parsing on-demand.
    self._option_registrations.append((args, kwargs))
    if self._parent_parser:
      for arg in args:
        existing_scope = self._parent_parser._existing_scope(arg)
        if existing_scope is not None:
          raise Shadowing(self.scope, arg, outer_scope=self._scope_str(existing_scope))
    for arg in args:
      if arg in self._known_args:
        raise OptionAlreadyRegistered(self.scope, arg)
    self._known_args.update(args)

  def _check_deprecated(self, dest, kwargs):
    """Checks option for deprecation and issues a warning/error if necessary."""
    removal_version = kwargs.get('removal_version', None)
    if removal_version is not None:
      warn_or_error(
        removal_version=removal_version,
        deprecated_entity_description="option '{}' in {}".format(dest, self._scope_str()),
        deprecation_start_version=kwargs.get('deprecation_start_version', None),
        hint=kwargs.get('removal_hint', None),
        stacklevel=9999)  # Out of range stacklevel to suppress printing src line.

  _allowed_registration_kwargs = {
    'type', 'member_type', 'choices', 'dest', 'default', 'implicit_value', 'metavar',
    'help', 'advanced', 'recursive', 'recursive_root', 'registering_class',
    'fingerprint', 'removal_version', 'removal_hint', 'deprecation_start_version', 'fromfile',
    'mutually_exclusive_group', 'daemon'
  }

  # TODO: Remove dict_option from here after deprecation is complete.
  _allowed_member_types = {
    str, int, float, dict, dir_option, dict_option, file_option, target_option
  }

  def _validate(self, args, kwargs):
    """Validate option registration arguments."""
    def error(exception_type, arg_name=None, **msg_kwargs):
      if arg_name is None:
        arg_name = args[0] if args else '<unknown>'
      raise exception_type(self.scope, arg_name, **msg_kwargs)

    if not args:
      error(NoOptionNames)
    # validate args.
    for arg in args:
      if not arg.startswith('-'):
        error(OptionNameDash, arg_name=arg)
      if not arg.startswith('--') and len(arg) > 2:
        error(OptionNameDoubleDash, arg_name=arg)

    # Validate kwargs.
    if 'implicit_value' in kwargs and kwargs['implicit_value'] is None:
      error(ImplicitValIsNone)

    # Note: we check for list here, not list_option, because we validate the provided kwargs,
    # not the ones we modified.  However we temporarily also allow list_option, until the
    # deprecation is complete.
    if 'member_type' in kwargs and kwargs.get('type', str) not in [list, list_option]:
      error(MemberTypeNotAllowed, type_=kwargs.get('type', str).__name__)

    if kwargs.get('member_type', str) not in self._allowed_member_types:
      error(InvalidMemberType, member_type=kwargs.get('member_type', str).__name__)

    for kwarg in kwargs:
      if kwarg not in self._allowed_registration_kwargs:
        error(InvalidKwarg, kwarg=kwarg)

      # Ensure `daemon=True` can't be passed on non-global scopes (except for `recursive=True`).
      if (kwarg == 'daemon' and self._scope != GLOBAL_SCOPE and kwargs.get('recursive') is False):
        error(InvalidKwargNonGlobalScope, kwarg=kwarg)

    removal_version = kwargs.get('removal_version')
    if removal_version is not None:
      validate_deprecation_semver(removal_version, 'removal version')

  def _existing_scope(self, arg):
    if arg in self._known_args:
      return self._scope
    elif self._parent_parser:
      return self._parent_parser._existing_scope(arg)
    else:
      return None

  _ENV_SANITIZER_RE = re.compile(r'[.-]')

  @staticmethod
  def parse_dest(*args, **kwargs):
    """Select the dest name for an option registration.

    If an explicit `dest` is specified, returns that and otherwise derives a default from the
    option flags where '--foo-bar' -> 'foo_bar' and '-x' -> 'x'.
    """
    explicit_dest = kwargs.get('dest')
    if explicit_dest:
      return explicit_dest

    arg = next((a for a in args if a.startswith('--')), args[0])
    return arg.lstrip('-').replace('-', '_')

  @staticmethod
  def _wrap_type(t):
    if t == list:
      return list_option
    elif t == dict:
      return dict_option
    else:
      return t

  @staticmethod
  def _convert_member_type(t, x):
    if t == dict:
      return dict_option(x).val
    else:
      return t(x)

  def _compute_value(self, dest, kwargs, flag_val_strs):
    """Compute the value to use for an option.

    The source of the default value is chosen according to the ranking in RankedValue.
    """
    # Helper function to convert a string to a value of the option's type.
    def to_value_type(val_str):
      if val_str is None:
        return None
      elif kwargs.get('type') == bool:
        return self._ensure_bool(val_str)
      else:
        type_arg = kwargs.get('type', str)
        try:
          return self._wrap_type(type_arg)(val_str)
        except TypeError as e:
          raise ParseError(
            "Error applying type '{}' to option value '{}', for option '--{}' in {}: {}"
            .format(type_arg.__name__, val_str, dest, self._scope_str(), e))

    # Helper function to expand a fromfile=True value string, if needed.
    # May return a string or a dict/list decoded from a json/yaml file.
    def expand(val_or_str):
      if (kwargs.get('fromfile', True) and val_or_str and
          isinstance(val_or_str, str) and val_or_str.startswith('@')):
        if val_or_str.startswith('@@'):   # Support a literal @ for fromfile values via @@.
          return val_or_str[1:]
        else:
          fromfile = val_or_str[1:]
          try:
            with open(fromfile, 'r') as fp:
              s = fp.read().strip()
              if fromfile.endswith('.json'):
                return json.loads(s)
              elif fromfile.endswith('.yml') or fromfile.endswith('.yaml'):
                return yaml.safe_load(s)
              else:
                return s
          except (IOError, ValueError, yaml.YAMLError) as e:
            raise self.FromfileError('Failed to read {} in {} from file {}: {}'.format(
                dest, self._scope_str(), fromfile, e))
      else:
        return val_or_str

    # Get value from config files, and capture details about its derivation.
    config_details = None
    config_section = GLOBAL_SCOPE_CONFIG_SECTION if self._scope == GLOBAL_SCOPE else self._scope
    config_default_val_or_str = expand(self._config.get(Config.DEFAULT_SECTION, dest, default=None))
    config_val_or_str = expand(self._config.get(config_section, dest, default=None))
    config_source_file = (self._config.get_source_for_option(config_section, dest) or
        self._config.get_source_for_option(Config.DEFAULT_SECTION, dest))
    if config_source_file is not None:
      config_source_file = os.path.relpath(config_source_file)
      config_details = 'in {}'.format(config_source_file)

    # Get value from environment, and capture details about its derivation.
    udest = dest.upper()
    if self._scope == GLOBAL_SCOPE:
      # For convenience, we allow three forms of env var for global scope options.
      # The fully-specified env var is PANTS_GLOBAL_FOO, which is uniform with PANTS_<SCOPE>_FOO
      # for all the other scopes.  However we also allow simply PANTS_FOO. And if the option name
      # itself starts with 'pants-' then we also allow simply FOO. E.g., PANTS_WORKDIR instead of
      # PANTS_PANTS_WORKDIR or PANTS_GLOBAL_PANTS_WORKDIR. We take the first specified value we
      # find, in this order: PANTS_GLOBAL_FOO, PANTS_FOO, FOO.
      env_vars = ['PANTS_GLOBAL_{0}'.format(udest), 'PANTS_{0}'.format(udest)]
      if udest.startswith('PANTS_'):
        env_vars.append(udest)
    else:
      sanitized_env_var_scope = self._ENV_SANITIZER_RE.sub('_', self._scope.upper())
      env_vars = ['PANTS_{0}_{1}'.format(sanitized_env_var_scope, udest)]

    env_val_or_str = None
    env_details = None
    if self._env:
      for env_var in env_vars:
        if env_var in self._env:
          env_val_or_str = expand(self._env.get(env_var))
          env_details = 'from env var {}'.format(env_var)
          break

    # Get value from cmd-line flags.
    flag_vals = [to_value_type(expand(x)) for x in flag_val_strs]
    if is_list_option(kwargs):
      # Note: It's important to set flag_val to None if no flags were specified, so we can
      # distinguish between no flags set vs. explicit setting of the value to [].
      flag_val = ListValueComponent.merge(flag_vals) if flag_vals else None
    elif is_dict_option(kwargs):
      # Note: It's important to set flag_val to None if no flags were specified, so we can
      # distinguish between no flags set vs. explicit setting of the value to {}.
      flag_val = DictValueComponent.merge(flag_vals) if flag_vals else None
    elif len(flag_vals) > 1:
      raise ParseError('Multiple cmd line flags specified for option {} in {}'.format(
          dest, self._scope_str()))
    elif len(flag_vals) == 1:
      flag_val = flag_vals[0]
    else:
      flag_val = None

    # Rank all available values.
    # Note that some of these values may already be of the value type, but type conversion
    # is idempotent, so this is OK.

    values_to_rank = [to_value_type(x) for x in
                      [flag_val, env_val_or_str, config_val_or_str,
                       config_default_val_or_str, kwargs.get('default'), None]]
    # Note that ranked_vals will always have at least one element, and all elements will be
    # instances of RankedValue (so none will be None, although they may wrap a None value).
    ranked_vals = list(reversed(list(RankedValue.prioritized_iter(*values_to_rank))))

    def record_option(value, rank, option_details=None):
      deprecation_version = kwargs.get('removal_version')
      self._option_tracker.record_option(scope=self._scope,
                                         option=dest,
                                         value=value,
                                         rank=rank,
                                         deprecation_version=deprecation_version,
                                         details=option_details)

    # Record info about the derivation of each of the contributing values.
    detail_history = []
    for ranked_val in ranked_vals:
      if ranked_val.rank in (RankedValue.CONFIG, RankedValue.CONFIG_DEFAULT):
        details = config_details
      elif ranked_val.rank == RankedValue.ENVIRONMENT:
        details = env_details
      else:
        details = None
      if details:
        detail_history.append(details)
      record_option(value=ranked_val.value, rank=ranked_val.rank, option_details=details)

    # Helper function to check various validity constraints on final option values.
    def check(val):
      if val is not None:
        choices = kwargs.get('choices')
        # If the `type` argument has an `all_variants` attribute, use that as `choices` if not
        # already set. Using an attribute instead of checking a subclass allows `type` arguments
        # which are functions to have an implicit fallback `choices` set as well.
        if choices is None and 'type' in kwargs:
          type_arg = kwargs.get('type')
          if hasattr(type_arg, 'all_variants'):
            choices = list(type_arg.all_variants)
        # TODO: convert this into an enum() pattern match!
        if choices is not None and val not in choices:
          raise ParseError('`{}` is not an allowed value for option {} in {}. '
                           'Must be one of: {}'.format(val, dest, self._scope_str(), choices))
        elif kwargs.get('type') == dir_option and not os.path.isdir(val):
          raise ParseError('Directory value `{}` for option {} in {} does not exist.'.format(
              val, dest, self._scope_str()))
        elif kwargs.get('type') == file_option and not os.path.isfile(val):
          raise ParseError('File value `{}` for option {} in {} does not exist.'.format(
              val, dest, self._scope_str()))

    # Generate the final value from all available values, and check that it (or its members,
    # if a list) are in the set of allowed choices.
    if is_list_option(kwargs):
      merged_rank = ranked_vals[-1].rank
      merged_val = ListValueComponent.merge(
          [rv.value for rv in ranked_vals if rv.value is not None]).val
      # TODO: run `check()` for all elements of a list option too!!!
      merged_val = [self._convert_member_type(kwargs.get('member_type', str), x)
                    for x in merged_val]
      for val in merged_val:
        check(val)
      ret = RankedValue(merged_rank, merged_val)
    elif is_dict_option(kwargs):
      # TODO: convert `member_type` for dict values too!
      merged_rank = ranked_vals[-1].rank
      merged_val = DictValueComponent.merge(
          [rv.value for rv in ranked_vals if rv.value is not None]).val
      for val in merged_val:
        check(val)
      ret = RankedValue(merged_rank, merged_val)
    else:
      ret = ranked_vals[-1]
      check(ret.value)

    # Record info about the derivation of the final value.
    merged_details = ', '.join(detail_history) if detail_history else None
    record_option(value=ret.value, rank=ret.rank, option_details=merged_details)

    # All done!
    return ret

  def _inverse_arg(self, arg):
    if arg.startswith('--'):
      if arg.startswith('--no-'):
        raise BooleanOptionNameWithNo(self.scope, arg)
      return '--no-{}'.format(arg[2:])
    else:
      return None

  def _register_child_parser(self, child):
    self._child_parsers.append(child)

  def _freeze(self):
    self._frozen = True

  def _scope_str(self, scope=None):
    scope = scope or self.scope
    return 'global scope' if scope == GLOBAL_SCOPE else "scope '{}'".format(scope)

  def __str__(self):
    return 'Parser({})'.format(self._scope)
