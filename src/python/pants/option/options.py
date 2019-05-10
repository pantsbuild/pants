# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import re
import sys
from builtins import object, open, str

from future.utils import text_type

from pants.base.deprecated import warn_or_error
from pants.option.arg_splitter import GLOBAL_SCOPE, ArgSplitter
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.option_tracker import OptionTracker
from pants.option.option_util import is_list_option
from pants.option.option_value_container import OptionValueContainer
from pants.option.parser import Parser
from pants.option.parser_hierarchy import ParserHierarchy, all_enclosing_scopes, enclosing_scope
from pants.option.scope import ScopeInfo
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import datatype


def make_flag_regex(long_name, short_name=None):
  long_esc = re.escape(long_name)
  if short_name:
    short_esc = re.escape(short_name)
    rx_str = r"\A(?:\-({short_esc})|\-\-(?:(no)\-)?({long_esc})(?:=(.*))?)\Z".format(
      short_esc=short_esc, long_esc=long_esc)
  else:
    rx_str = r"\A\-\-(?:(no)\-)?({long_esc})(?:=(.*))?\Z".format(long_esc=long_esc)
  return re.compile(rx_str)


class Options(object):
  """The outward-facing API for interacting with options.

  Supports option registration and fetching option values.

  Examples:

  The value in global scope of option '--foo-bar' (registered in global scope) will be selected
  in the following order:
    - The value of the --foo-bar flag in global scope.
    - The value of the PANTS_GLOBAL_FOO_BAR environment variable.
    - The value of the PANTS_FOO_BAR environment variable.
    - The value of the foo_bar key in the [GLOBAL] section of pants.ini.
    - The hard-coded value provided at registration time.
    - None.

  The value in scope 'compile.java' of option '--foo-bar' (registered in global scope) will be
  selected in the following order:
    - The value of the --foo-bar flag in scope 'compile.java'.
    - The value of the --foo-bar flag in scope 'compile'.
    - The value of the --foo-bar flag in global scope.
    - The value of the PANTS_COMPILE_JAVA_FOO_BAR environment variable.
    - The value of the PANTS_COMPILE_FOO_BAR environment variable.
    - The value of the PANTS_GLOBAL_FOO_BAR environment variable.
    - The value of the PANTS_FOO_BAR environment variable.
    - The value of the foo_bar key in the [compile.java] section of pants.ini.
    - The value of the foo_bar key in the [compile] section of pants.ini.
    - The value of the foo_bar key in the [GLOBAL] section of pants.ini.
    - The hard-coded value provided at registration time.
    - None.

  The value in scope 'compile.java' of option '--foo-bar' (registered in scope 'compile') will be
  selected in the following order:
    - The value of the --foo-bar flag in scope 'compile.java'.
    - The value of the --foo-bar flag in scope 'compile'.
    - The value of the PANTS_COMPILE_JAVA_FOO_BAR environment variable.
    - The value of the PANTS_COMPILE_FOO_BAR environment variable.
    - The value of the foo_bar key in the [compile.java] section of pants.ini.
    - The value of the foo_bar key in the [compile] section of pants.ini.
    - The value of the foo_bar key in the [GLOBAL] section of pants.ini
      (because of automatic config file fallback to that section).
    - The hard-coded value provided at registration time.
    - None.
  """

  class FrozenOptionsError(Exception):
    """Options are frozen and can't be mutated."""

  class DuplicateScopeError(Exception):
    """More than one registration occurred for the same scope."""

  @classmethod
  def complete_scopes(cls, scope_infos):
    """Expand a set of scopes to include all enclosing scopes.

    E.g., if the set contains `foo.bar.baz`, ensure that it also contains `foo.bar` and `foo`.

    Also adds any deprecated scopes.
    """
    ret = {GlobalOptionsRegistrar.get_scope_info()}
    original_scopes = dict()
    for si in scope_infos:
      ret.add(si)
      if si.scope in original_scopes:
        raise cls.DuplicateScopeError('Scope `{}` claimed by {}, was also claimed by {}.'.format(
            si.scope, si, original_scopes[si.scope]
          ))
      original_scopes[si.scope] = si
      if si.deprecated_scope:
        ret.add(ScopeInfo(si.deprecated_scope, si.category, si.optionable_cls))
        original_scopes[si.deprecated_scope] = si

    # TODO: Once scope name validation is enforced (so there can be no dots in scope name
    # components) we can replace this line with `for si in scope_infos:`, because it will
    # not be possible for a deprecated_scope to introduce any new intermediate scopes.
    for si in copy.copy(ret):
      for scope in all_enclosing_scopes(si.scope, allow_global=False):
        if scope not in original_scopes:
          ret.add(ScopeInfo(scope, ScopeInfo.INTERMEDIATE))
    return ret

  @classmethod
  def create(cls, env, config, known_scope_infos, args=None, bootstrap_option_values=None):
    """Create an Options instance.

    :param env: a dict of environment variables.
    :param :class:`pants.option.config.Config` config: data from a config file.
    :param known_scope_infos: ScopeInfos for all scopes that may be encountered.
    :param args: a list of cmd-line args; defaults to `sys.argv` if None is supplied.
    :param bootstrap_option_values: An optional namespace containing the values of bootstrap
           options. We can use these values when registering other options.
    """
    # We need parsers for all the intermediate scopes, so inherited option values
    # can propagate through them.
    complete_known_scope_infos = cls.complete_scopes(known_scope_infos)
    splitter = ArgSplitter(complete_known_scope_infos)
    args = sys.argv if args is None else args
    goals, scope_to_flags, target_specs, passthru, passthru_owner, unknown_scopes = splitter.split_args(args)

    option_tracker = OptionTracker()

    if bootstrap_option_values:
      target_spec_files = bootstrap_option_values.target_spec_files
      if target_spec_files:
        for spec in target_spec_files:
          with open(spec, 'r') as f:
            target_specs.extend([line for line in [line.strip() for line in f] if line])

    help_request = splitter.help_request

    parser_hierarchy = ParserHierarchy(env, config, complete_known_scope_infos, option_tracker)
    bootstrap_option_values = bootstrap_option_values
    known_scope_to_info = {s.scope: s for s in complete_known_scope_infos}
    return cls(goals, scope_to_flags, target_specs, passthru, passthru_owner, help_request,
               parser_hierarchy, bootstrap_option_values, known_scope_to_info,
               option_tracker, unknown_scopes)

  def __init__(self, goals, scope_to_flags, target_specs, passthru, passthru_owner, help_request,
               parser_hierarchy, bootstrap_option_values, known_scope_to_info,
               option_tracker, unknown_scopes):
    """The low-level constructor for an Options instance.

    Dependees should use `Options.create` instead.
    """
    self._goals = goals
    self._scope_to_flags = scope_to_flags
    self._target_specs = target_specs
    self._passthru = passthru
    self._passthru_owner = passthru_owner
    self._help_request = help_request
    self._parser_hierarchy = parser_hierarchy
    self._bootstrap_option_values = bootstrap_option_values
    self._known_scope_to_info = known_scope_to_info
    self._option_tracker = option_tracker
    self._frozen = False
    self._unknown_scopes = unknown_scopes

  # TODO: Eliminate this in favor of a builder/factory.
  @property
  def frozen(self):
    """Whether or not this Options object is frozen from writes."""
    return self._frozen

  @property
  def tracker(self):
    return self._option_tracker

  @property
  def help_request(self):
    """
    :API: public
    """
    return self._help_request

  @property
  def target_specs(self):
    """The targets to operate on.

    :API: public
    """
    return self._target_specs

  @property
  def goals(self):
    """The requested goals, in the order specified on the cmd line.

    :API: public
    """
    return self._goals

  @memoized_property
  def goals_by_version(self):
    """Goals organized into three tuples by whether they are v1, ambiguous, or v2 goals (respectively).

    It's possible for a goal to be implemented with both v1 and v2, in which case a consumer
    should use the `--v1` and `--v2` global flags to disambiguate.
    """
    v1, ambiguous, v2 = [], [], []
    for goal in self._goals:
      goal_dot = '{}.'.format(goal)
      scope_categories = {s.category
                          for s in self.known_scope_to_info.values()
                          if s.scope == goal or s.scope.startswith(goal_dot)}
      is_v1 = ScopeInfo.TASK in scope_categories
      is_v2 = ScopeInfo.GOAL in scope_categories
      if is_v1 and is_v2:
        ambiguous.append(goal)
      elif is_v1:
        v1.append(goal)
      else:
        v2.append(goal)
    return tuple(v1), tuple(ambiguous), tuple(v2)

  @property
  def known_scope_to_info(self):
    return self._known_scope_to_info

  @property
  def scope_to_flags(self):
    return self._scope_to_flags

  def freeze(self):
    """Freezes this Options instance."""
    self._frozen = True

  def drop_flag_values(self):
    """Returns a copy of these options that ignores values specified via flags.

    Any pre-cached option values are cleared and only option values that come from option defaults,
    the config or the environment are used.
    """
    # An empty scope_to_flags to force all values to come via the config -> env hierarchy alone
    # and empty values in case we already cached some from flags.
    no_flags = {}
    return Options(self._goals,
                   no_flags,
                   self._target_specs,
                   self._passthru,
                   self._passthru_owner,
                   self._help_request,
                   self._parser_hierarchy,
                   self._bootstrap_option_values,
                   self._known_scope_to_info,
                   self._option_tracker,
                   self._unknown_scopes)

  def is_known_scope(self, scope):
    """Whether the given scope is known by this instance.

    :API: public
    """
    return scope in self._known_scope_to_info

  def passthru_args_for_scope(self, scope):
    # Passthru args "belong" to the last scope mentioned on the command-line.

    # Note: If that last scope is a goal, we allow all tasks in that goal to access the passthru
    # args. This is to allow the more intuitive
    # pants run <target> -- <passthru args>
    # instead of requiring
    # pants run.py <target> -- <passthru args>.
    #
    # However note that in the case where multiple tasks run in the same goal, e.g.,
    # pants test <target> -- <passthru args>
    # Then, e.g., both junit and pytest will get the passthru args even though the user probably
    # only intended them to go to one of them. If the wrong one is not a no-op then the error will
    # be unpredictable. However this is  not a common case, and can be circumvented with an
    # explicit test.pytest or test.junit scope.
    if (scope and self._passthru_owner and scope.startswith(self._passthru_owner) and
          (len(scope) == len(self._passthru_owner) or scope[len(self._passthru_owner)] == '.')):
      return self._passthru
    else:
      return []

  def _assert_not_frozen(self):
    if self._frozen:
      raise self.FrozenOptionsError('cannot mutate frozen Options instance {!r}.'.format(self))

  def register(self, scope, *args, **kwargs):
    """Register an option in the given scope."""
    self._assert_not_frozen()
    self.get_parser(scope).register(*args, **kwargs)
    deprecated_scope = self.known_scope_to_info[scope].deprecated_scope
    if deprecated_scope:
      self.get_parser(deprecated_scope).register(*args, **kwargs)

  def registration_function_for_optionable(self, optionable_class):
    """Returns a function for registering options on the given scope."""
    self._assert_not_frozen()
    # TODO(benjy): Make this an instance of a class that implements __call__, so we can
    # docstring it, and so it's less weird than attatching properties to a function.
    def register(*args, **kwargs):
      kwargs['registering_class'] = optionable_class
      self.register(optionable_class.options_scope, *args, **kwargs)
    # Clients can access the bootstrap option values as register.bootstrap.
    register.bootstrap = self.bootstrap_option_values()
    # Clients can access the scope as register.scope.
    register.scope = optionable_class.options_scope
    return register

  def get_parser(self, scope):
    """Returns the parser for the given scope, so code can register on it directly."""
    self._assert_not_frozen()
    return self._parser_hierarchy.get_parser_by_scope(scope)

  def walk_parsers(self, callback):
    self._assert_not_frozen()
    self._parser_hierarchy.walk(callback)

  def _check_and_apply_deprecations(self, scope, values):
    """Checks whether a ScopeInfo has options specified in a deprecated scope.

    There are two related cases here. Either:
      1) The ScopeInfo has an associated deprecated_scope that was replaced with a non-deprecated
         scope, meaning that the options temporarily live in two locations.
      2) The entire ScopeInfo is deprecated (as in the case of deprecated SubsystemDependencies),
         meaning that the options live in one location.

    In the first case, this method has the sideeffect of merging options values from deprecated
    scopes into the given values.
    """
    si = self.known_scope_to_info[scope]

    # If this Scope is itself deprecated, report that.
    if si.removal_version:
      explicit_keys = self.for_scope(scope, inherit_from_enclosing_scope=False).get_explicit_keys()
      if explicit_keys:
        warn_or_error(
            removal_version=si.removal_version,
            deprecated_entity_description='scope {}'.format(scope),
            hint=si.removal_hint,
          )

    # Check if we're the new name of a deprecated scope, and clone values from that scope.
    # Note that deprecated_scope and scope share the same Optionable class, so deprecated_scope's
    # Optionable has a deprecated_options_scope equal to deprecated_scope. Therefore we must
    # check that scope != deprecated_scope to prevent infinite recursion.
    deprecated_scope = si.deprecated_scope
    if deprecated_scope is not None and scope != deprecated_scope:
      # Do the deprecation check only on keys that were explicitly set on the deprecated scope
      # (and not on its enclosing scopes).
      explicit_keys = self.for_scope(deprecated_scope,
                                     inherit_from_enclosing_scope=False).get_explicit_keys()
      if explicit_keys:
        # Update our values with those of the deprecated scope (now including values inherited
        # from its enclosing scope).
        # Note that a deprecated val will take precedence over a val of equal rank.
        # This makes the code a bit neater.
        values.update(self.for_scope(deprecated_scope))

        warn_or_error(
            removal_version=self.known_scope_to_info[scope].deprecated_scope_removal_version,
            deprecated_entity_description='scope {}'.format(deprecated_scope),
            hint='Use scope {} instead (options: {})'.format(scope, ', '.join(explicit_keys))
          )

  class _ScopedFlagNameForFuzzyMatching(datatype([
      ('scope', text_type),
      ('arg', text_type),
      ('normalized_arg', text_type),
      ('scoped_arg', text_type),
  ])):
    """Specify how a registered option would look like on the command line.

    This information enables fuzzy matching to suggest correct option names when a user specifies an
    unregistered option on the command line.

    :param scope: the 'scope' component of a command-line flag.
    :param arg: the unscoped flag name as it would appear on the command line.
    :param normalized_arg: the fully-scoped option name, without any leading dashes.
    :param scoped_arg: the fully-scoped option as it would appear on the command line.
    """

    def __new__(cls, scope, arg):
      normalized_arg = re.sub('^-+', '', arg)
      if scope == GLOBAL_SCOPE:
        scoped_arg = arg
      else:
        dashed_scope = scope.replace('.', '-')
        scoped_arg = '--{}-{}'.format(dashed_scope, normalized_arg)
      return super(Options._ScopedFlagNameForFuzzyMatching, cls).__new__(
        cls,
        scope=scope,
        arg=arg,
        normalized_arg=normalized_arg,
        scoped_arg=scoped_arg)

    @property
    def normalized_scoped_arg(self):
      return re.sub(r'^-+', '', self.scoped_arg)

  @memoized_property
  def _all_scoped_flag_names_for_fuzzy_matching(self):
    """A list of all registered flags in all their registered scopes.

    This list is used for fuzzy matching against unrecognized option names across registered
    scopes on the command line.
    """
    all_scoped_flag_names = []
    def register_all_scoped_names(parser):
      scope = parser.scope
      known_args = parser.known_args
      for arg in known_args:
        scoped_flag = self._ScopedFlagNameForFuzzyMatching(
          scope=text_type(scope),
          arg=text_type(arg),
        )
        all_scoped_flag_names.append(scoped_flag)
    self.walk_parsers(register_all_scoped_names)
    return sorted(all_scoped_flag_names, key=lambda flag_info: flag_info.scoped_arg)

  def _make_parse_args_request(self, flags_in_scope, namespace):
    levenshtein_max_distance = (
      self._bootstrap_option_values.option_name_check_distance
      if self._bootstrap_option_values
      else 0
    )
    return Parser.ParseArgsRequest(
      flags_in_scope=flags_in_scope,
      namespace=namespace,
      get_all_scoped_flag_names=lambda: self._all_scoped_flag_names_for_fuzzy_matching,
      levenshtein_max_distance=levenshtein_max_distance,
    )

  # TODO: Eagerly precompute backing data for this?
  @memoized_method
  def for_scope(self, scope, inherit_from_enclosing_scope=True):
    """Return the option values for the given scope.

    Values are attributes of the returned object, e.g., options.foo.
    Computed lazily per scope.

    :API: public
    """

    # First get enclosing scope's option values, if any.
    if scope == GLOBAL_SCOPE or not inherit_from_enclosing_scope:
      values = OptionValueContainer()
    else:
      values = copy.copy(self.for_scope(enclosing_scope(scope)))

    # Now add our values.
    flags_in_scope = self._scope_to_flags.get(scope, [])
    parse_args_request = self._make_parse_args_request(flags_in_scope, values)
    self._parser_hierarchy.get_parser_by_scope(scope).parse_args(parse_args_request)

    # Check for any deprecation conditions, which are evaluated using `self._flag_matchers`.
    if inherit_from_enclosing_scope:
      self._check_and_apply_deprecations(scope, values)

    return values

  def get_fingerprintable_for_scope(self, bottom_scope, include_passthru=False,
                                    fingerprint_key=None, invert=False):
    """Returns a list of fingerprintable (option type, option value) pairs for the given scope.

    Fingerprintable options are options registered via a "fingerprint=True" kwarg. This flag
    can be parameterized with `fingerprint_key` for special cases.

    This method also searches enclosing options scopes of `bottom_scope` to determine the set of
    fingerprintable pairs.

    :param str bottom_scope: The scope to gather fingerprintable options for.
    :param bool include_passthru: Whether to include passthru args captured by `bottom_scope` in the
                                  fingerprintable options.
    :param string fingerprint_key: The option kwarg to match against (defaults to 'fingerprint').
    :param bool invert: Whether or not to invert the boolean check for the fingerprint_key value.

    :API: public
    """
    fingerprint_key = fingerprint_key or 'fingerprint'
    fingerprint_default = bool(invert)
    pairs = []

    if include_passthru:
      # Passthru args can only be sent to outermost scopes so we gather them once here up-front.
      passthru_args = self.passthru_args_for_scope(bottom_scope)
      # NB: We can't sort passthru args, the underlying consumer may be order-sensitive.
      pairs.extend((str, pass_arg) for pass_arg in passthru_args)

    # Note that we iterate over options registered at `bottom_scope` and at all
    # enclosing scopes, since option-using code can read those values indirectly
    # via its own OptionValueContainer, so they can affect that code's output.
    for registration_scope in all_enclosing_scopes(bottom_scope):
      parser = self._parser_hierarchy.get_parser_by_scope(registration_scope)
      # Sort the arguments, so that the fingerprint is consistent.
      for (_, kwargs) in sorted(parser.option_registrations_iter()):
        if kwargs.get('recursive', False) and not kwargs.get('recursive_root', False):
          continue  # We only need to fprint recursive options once.
        if kwargs.get(fingerprint_key, fingerprint_default) is not True:
          continue
        # Note that we read the value from scope, even if the registration was on an enclosing
        # scope, to get the right value for recursive options (and because this mirrors what
        # option-using code does).
        val = self.for_scope(bottom_scope)[kwargs['dest']]
        # If we have a list then we delegate to the fingerprinting implementation of the members.
        if is_list_option(kwargs):
          val_type = kwargs.get('member_type', str)
        else:
          val_type = kwargs.get('type', str)
        pairs.append((val_type, val))
    return pairs

  def __getitem__(self, scope):
    # TODO(John Sirois): Mainly supports use of dict<str, dict<str, str>> for mock options in tests,
    # Consider killing if tests consolidate on using TestOptions instead of the raw dicts.
    return self.for_scope(scope)

  def bootstrap_option_values(self):
    """Return the option values for bootstrap options.

    General code can also access these values in the global scope.  But option registration code
    cannot, hence this special-casing of this small set of options.
    """
    return self._bootstrap_option_values

  def for_global_scope(self):
    """Return the option values for the global scope.

    :API: public
    """
    return self.for_scope(GLOBAL_SCOPE)
