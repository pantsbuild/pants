# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import sys

from pants.base.deprecated import warn_or_error
from pants.option.arg_splitter import GLOBAL_SCOPE, ArgSplitter
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.option_util import is_list_option
from pants.option.option_value_container import OptionValueContainer
from pants.option.parser_hierarchy import ParserHierarchy, all_enclosing_scopes, enclosing_scope
from pants.option.scope import ScopeInfo


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

  class OptionTrackerRequiredError(Exception):
    """Options requires an OptionTracker instance."""

  @classmethod
  def complete_scopes(cls, scope_infos):
    """Expand a set of scopes to include all enclosing scopes.

    E.g., if the set contains `foo.bar.baz`, ensure that it also contains `foo.bar` and `foo`.

    Also adds any deprecated scopes.
    """
    ret = {GlobalOptionsRegistrar.get_scope_info()}
    original_scopes = set()
    for si in scope_infos:
      ret.add(si)
      original_scopes.add(si.scope)
      if si.deprecated_scope:
        ret.add(ScopeInfo(si.deprecated_scope, si.category, si.optionable_cls))
        original_scopes.add(si.deprecated_scope)

    # TODO: Once scope name validation is enforced (so there can be no dots in scope name
    # components) we can replace this line with `for si in scope_infos:`, because it will
    # not be possible for a deprecated_scope to introduce any new intermediate scopes.
    for si in copy.copy(ret):
      for scope in all_enclosing_scopes(si.scope, allow_global=False):
        if scope not in original_scopes:
          ret.add(ScopeInfo(scope, ScopeInfo.INTERMEDIATE))
    return ret

  @classmethod
  def create(cls, env, config, known_scope_infos, args=None, bootstrap_option_values=None,
             option_tracker=None):
    """Create an Options instance.

    :param env: a dict of environment variables.
    :param :class:`pants.option.config.Config` config: data from a config file.
    :param known_scope_infos: ScopeInfos for all scopes that may be encountered.
    :param args: a list of cmd-line args; defaults to `sys.argv` if None is supplied.
    :param bootstrap_option_values: An optional namespace containing the values of bootstrap
           options. We can use these values when registering other options.
    :param :class:`pants.option.option_tracker.OptionTracker` option_tracker: option tracker
           instance to record how option values were assigned.
    """
    # We need parsers for all the intermediate scopes, so inherited option values
    # can propagate through them.
    complete_known_scope_infos = cls.complete_scopes(known_scope_infos)
    splitter = ArgSplitter(complete_known_scope_infos)
    args = sys.argv if args is None else args
    goals, scope_to_flags, target_specs, passthru, passthru_owner = splitter.split_args(args)

    if not option_tracker:
      raise cls.OptionTrackerRequiredError()

    if bootstrap_option_values:
      target_spec_files = bootstrap_option_values.target_spec_files
      if target_spec_files:
        for spec in target_spec_files:
          with open(spec) as f:
            target_specs.extend(filter(None, [line.strip() for line in f]))

    help_request = splitter.help_request

    parser_hierarchy = ParserHierarchy(env, config, complete_known_scope_infos, option_tracker)
    values_by_scope = {}  # Arg values, parsed per-scope on demand.
    bootstrap_option_values = bootstrap_option_values
    known_scope_to_info = {s.scope: s for s in complete_known_scope_infos}
    return cls(goals, scope_to_flags, target_specs, passthru, passthru_owner, help_request,
               parser_hierarchy, values_by_scope, bootstrap_option_values, known_scope_to_info,
               option_tracker)

  def __init__(self, goals, scope_to_flags, target_specs, passthru, passthru_owner, help_request,
               parser_hierarchy, values_by_scope, bootstrap_option_values, known_scope_to_info,
               option_tracker):
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
    self._values_by_scope = values_by_scope
    self._bootstrap_option_values = bootstrap_option_values
    self._known_scope_to_info = known_scope_to_info
    self._option_tracker = option_tracker

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

  @property
  def known_scope_to_info(self):
    return self._known_scope_to_info

  @property
  def scope_to_flags(self):
    return self._scope_to_flags

  def drop_flag_values(self):
    """Returns a copy of these options that ignores values specified via flags.

    Any pre-cached option values are cleared and only option values that come from option defaults,
    the config or the environment are used.
    """
    # An empty scope_to_flags to force all values to come via the config -> env hierarchy alone
    # and empty values in case we already cached some from flags.
    no_flags = {}
    no_values = {}
    return Options(self._goals,
                   no_flags,
                   self._target_specs,
                   self._passthru,
                   self._passthru_owner,
                   self._help_request,
                   self._parser_hierarchy,
                   no_values,
                   self._bootstrap_option_values,
                   self._known_scope_to_info,
                   self._option_tracker)

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

  def register(self, scope, *args, **kwargs):
    """Register an option in the given scope."""
    self.get_parser(scope).register(*args, **kwargs)
    deprecated_scope = self.known_scope_to_info[scope].deprecated_scope
    if deprecated_scope:
      self.get_parser(deprecated_scope).register(*args, **kwargs)

  def registration_function_for_optionable(self, optionable_class):
    """Returns a function for registering options on the given scope."""
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
    return self._parser_hierarchy.get_parser_by_scope(scope)

  def walk_parsers(self, callback):
    self._parser_hierarchy.walk(callback)

  def for_scope(self, scope, inherit_from_enclosing_scope=True):
    """Return the option values for the given scope.

    Values are attributes of the returned object, e.g., options.foo.
    Computed lazily per scope.

    :API: public
    """
    # Short-circuit, if already computed.
    if scope in self._values_by_scope:
      return self._values_by_scope[scope]

    # First get enclosing scope's option values, if any.
    if scope == GLOBAL_SCOPE or not inherit_from_enclosing_scope:
      values = OptionValueContainer()
    else:
      values = copy.copy(self.for_scope(enclosing_scope(scope)))

    # Now add our values.
    flags_in_scope = self._scope_to_flags.get(scope, [])
    self._parser_hierarchy.get_parser_by_scope(scope).parse_args(flags_in_scope, values)

    # If we're the new name of a deprecated scope, also get values from that scope.
    deprecated_scope = self.known_scope_to_info[scope].deprecated_scope
    # Note that deprecated_scope and scope share the same Optionable class, so deprecated_scope's
    # Optionable has a deprecated_options_scope equal to deprecated_scope. Therefore we must
    # check that scope != deprecated_scope to prevent infinite recursion.
    if deprecated_scope is not None and scope != deprecated_scope:
      # Do the deprecation check only on keys that were explicitly set on the deprecated scope
      # (and not on its enclosing scopes).
      explicit_keys = self.for_scope(deprecated_scope,
                                     inherit_from_enclosing_scope=False).get_explicit_keys()
      if explicit_keys:
        warn_or_error(self.known_scope_to_info[scope].deprecated_scope_removal_version,
                      'scope {}'.format(deprecated_scope),
                      'Use scope {} instead (options: {})'.format(scope, ', '.join(explicit_keys)))
        # Update our values with those of the deprecated scope (now including values inherited
        # from its enclosing scope).
        # Note that a deprecated val will take precedence over a val of equal rank.
        # This makes the code a bit neater.
        values.update(self.for_scope(deprecated_scope))

    # Cache the values.
    self._values_by_scope[scope] = values

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
