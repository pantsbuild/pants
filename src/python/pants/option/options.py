# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import sys

from pants.base.build_environment import pants_release
from pants.option.arg_splitter import (GLOBAL_SCOPE, ArgSplitter, NoGoalHelp, OptionsHelp,
                                       UnknownGoalHelp)
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.option_value_container import OptionValueContainer
from pants.option.parser_hierarchy import ParserHierarchy
from pants.option.scope import ScopeInfo


class Options(object):
  """The outward-facing API for interacting with options.

  Supports option registration and fetching option values.

  Examples:

  The value in global scope of option '--foo-bar' (registered in global scope) will be selected
  in the following order:
    - The value of the --foo-bar flag in global scope.
    - The value of the PANTS_DEFAULT_FOO_BAR environment variable.
    - The value of the PANTS_FOO_BAR environment variable.
    - The value of the foo_bar key in the [DEFAULT] section of pants.ini.
    - The hard-coded value provided at registration time.
    - None.

  The value in scope 'compile.java' of option '--foo-bar' (registered in global scope) will be
  selected in the following order:
    - The value of the --foo-bar flag in scope 'compile.java'.
    - The value of the --foo-bar flag in scope 'compile'.
    - The value of the --foo-bar flag in global scope.
    - The value of the PANTS_COMPILE_JAVA_FOO_BAR environment variable.
    - The value of the PANTS_COMPILE_FOO_BAR environment variable.
    - The value of the PANTS_DEFAULT_FOO_BAR environment variable.
    - The value of the PANTS_FOO_BAR environment variable.
    - The value of the foo_bar key in the [compile.java] section of pants.ini.
    - The value of the foo_bar key in the [compile] section of pants.ini.
    - The value of the foo_bar key in the [DEFAULT] section of pants.ini.
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
    - The value of the foo_bar key in the [DEFAULT] section of pants.ini
      (because of automatic config file fallback to that section).
    - The hard-coded value provided at registration time.
    - None.
  """
  @classmethod
  def complete_scopes(cls, scope_infos):
    """Expand a set of scopes to include all enclosing scopes.

    E.g., if the set contains `foo.bar.baz`, ensure that it also contains `foo.bar` and `foo`.
    """
    ret = {GlobalOptionsRegistrar.get_scope_info()}
    for scope_info in scope_infos:
      ret.add(scope_info)

    original_scopes = {si.scope for si in scope_infos}
    for scope_info in scope_infos:
      scope = scope_info.scope
      while scope != '':
        if scope not in original_scopes:
          ret.add(ScopeInfo(scope, ScopeInfo.INTERMEDIATE))
        scope = scope.rpartition('.')[0]
    return ret

  @classmethod
  def create(cls, env, config, known_scope_infos, args=None, bootstrap_option_values=None):
    """Create an Options instance.

    :param env: a dict of environment variables.
    :param config: data from a config file (must support config.get[list](section, name, default=)).
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
    goals, scope_to_flags, target_specs, passthru, passthru_owner = splitter.split_args(args)

    if bootstrap_option_values:
      target_spec_files = bootstrap_option_values.target_spec_files
      if target_spec_files:
        for spec in target_spec_files:
          with open(spec) as f:
            target_specs.extend(filter(None, [line.strip() for line in f]))

    help_request = splitter.help_request

    parser_hierarchy = ParserHierarchy(env, config, complete_known_scope_infos)
    values_by_scope = {}  # Arg values, parsed per-scope on demand.
    bootstrap_option_values = bootstrap_option_values
    known_scope_to_info = {s.scope: s for s in complete_known_scope_infos}
    return cls(goals, scope_to_flags, target_specs, passthru, passthru_owner, help_request,
               parser_hierarchy, values_by_scope, bootstrap_option_values, known_scope_to_info)

  def __init__(self, goals, scope_to_flags, target_specs, passthru, passthru_owner, help_request,
               parser_hierarchy, values_by_scope, bootstrap_option_values, known_scope_to_info):
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
                   self._known_scope_to_info)

  @property
  def target_specs(self):
    """The targets to operate on."""
    return self._target_specs

  @property
  def goals(self):
    """The requested goals, in the order specified on the cmd line."""
    return self._goals

  def is_known_scope(self, scope):
    """Whether the given scope is known by this instance."""
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
    """Register an option in the given scope, using argparse params."""
    self.get_parser(scope).register(*args, **kwargs)

  def registration_function_for_optionable(self, optionable_class, scope):
    """Returns a function for registering argparse args on the given scope."""
    # TODO(benjy): Make this an instance of a class that implements __call__, so we can
    # docstring it, and so it's less weird than attatching properties to a function.
    def register(*args, **kwargs):
      kwargs['registering_class'] = optionable_class
      self.register(scope, *args, **kwargs)
    # Clients can access the bootstrap option values as register.bootstrap.
    register.bootstrap = self.bootstrap_option_values()
    # Clients can access the scope as register.scope.
    register.scope = scope
    return register

  def get_parser(self, scope):
    """Returns the parser for the given scope, so code can register on it directly."""
    return self._parser_hierarchy.get_parser_by_scope(scope)

  def walk_parsers(self, callback):
    self._parser_hierarchy.walk(callback)

  def for_scope(self, scope):
    """Return the option values for the given scope.

    Values are attributes of the returned object, e.g., options.foo.
    Computed lazily per scope.
    """
    # Short-circuit, if already computed.
    if scope in self._values_by_scope:
      return self._values_by_scope[scope]

    # First get enclosing scope's option values, if any.
    if scope == GLOBAL_SCOPE:
      values = OptionValueContainer()
    else:
      values = copy.deepcopy(self.for_scope(scope.rpartition('.')[0]))

    # Now add our values.
    flags_in_scope = self._scope_to_flags.get(scope, [])
    self._parser_hierarchy.get_parser_by_scope(scope).parse_args(flags_in_scope, values)
    self._values_by_scope[scope] = values
    return values

  def registration_args_iter_for_scope(self, scope):
    """Returns an iterator over the registration arguments of each option in this scope.

    See `Parser.registration_args_iter` for details.
    """
    return self._parser_hierarchy.get_parser_by_scope(scope).registration_args_iter()

  def get_fingerprintable_for_scope(self, scope):
    """Returns a list of fingerprintable (option type, option value) pairs for the given scope.

    Fingerprintable options are options registered via a "fingerprint=True" kwarg.
    """
    pairs = []
    # Note that we iterate over options registered at `scope` and at all enclosing scopes, since
    # option-using code can read those values indirectly via its own OptionValueContainer, so
    # they can affect that code's output.
    registration_scope = scope
    while registration_scope is not None:
      # This iterator will have already sorted the options, so their order is deterministic.
      for (name, _, kwargs) in self.registration_args_iter_for_scope(registration_scope):
        if kwargs.get('recursive') and not kwargs.get('recursive_root'):
          continue  # We only need to fprint recursive options once.
        if kwargs.get('fingerprint') is not True:
          continue
        # Note that we read the value from scope, even if the registration was on an enclosing
        # scope, to get the right value for recursive options (and because this mirrors what
        # option-using code does).
        val = self.for_scope(scope)[name]
        val_type = kwargs.get('type', '')
        pairs.append((val_type, val))
      registration_scope = (None if registration_scope == ''
                            else registration_scope.rpartition('.')[0])
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
    """Return the option values for the global scope."""
    return self.for_scope(GLOBAL_SCOPE)

  def print_help_if_requested(self):
    """If help was requested, print it and return True.

    Otherwise return False.
    """
    if self._help_request:
      def print_hint():
        print('Use `pants goals` to list goals.')
        print('Use `pants help` to get help.')
      if isinstance(self._help_request, OptionsHelp):
        self._print_options_help()
      elif isinstance(self._help_request, UnknownGoalHelp):
        print('Unknown goals: {}'.format(', '.join(self._help_request.unknown_goals)))
        print_hint()
        # TODO: Should probably cause a non-zero exit code.
      elif isinstance(self._help_request, NoGoalHelp):
        print('No goals specified.')
        print_hint()
        # TODO: Should probably cause a non-zero exit code.
      return True
    else:
      return False

  def _print_options_help(self):
    """Print a help screen.

    Assumes that self._help_request is an instance of OptionsHelp.

    Note: Ony useful if called after options have been registered.
    """
    show_all_help = self._help_request.all_scopes
    if show_all_help:
      help_scopes = self._known_scope_to_info.keys()
    else:
      # The scopes explicitly mentioned by the user on the cmd line.
      help_scopes = set(self._scope_to_flags.keys()) - set([GLOBAL_SCOPE])
      # Add all subscopes (e.g., so that `pants help compile` shows help for all tasks under
      # `compile`.) Note that sorting guarantees that we only need to check the immediate parent.
      for scope in sorted(self._known_scope_to_info.keys()):
        if scope.partition('.')[0] in help_scopes:
          help_scopes.add(scope)

    help_scope_infos = [self._known_scope_to_info[s] for s in sorted(help_scopes)]
    if help_scope_infos:
      for scope_info in help_scope_infos:
        help_str = self._format_options_help_for_scope(scope_info)
        if help_str:
          print(help_str)
      return
    else:
      print(pants_release())
      print('\nUsage:')
      print('  ./pants [option ...] [goal ...] [target...]  Attempt the specified goals.')
      print('  ./pants help                                 Get help.')
      print('  ./pants help [goal]                          Get help for a goal.')
      print('  ./pants help-advanced [goal]                 Get help for a goal\'s advanced options.')
      print('  ./pants help-all                             Get help for all goals.')
      print('  ./pants goals                                List all installed goals.')
      print('')
      print('  [target] accepts two special forms:')
      print('    dir:  to include all targets in the specified directory.')
      print('    dir:: to include all targets found recursively under the directory.')
      print('\nFriendly docs:\n  http://pantsbuild.github.io/')

      print(self.get_parser(GLOBAL_SCOPE).format_help('Global', 'Global options',
                                                      show_advanced=self._help_request.advanced))

  def _format_options_help_for_scope(self, scope_info):
    """Generate a help message for options at the specified scope.

    Assumes that self._help_request is an instance of OptionsHelp.

    :param scope_info: A ScopeInfo for the speicified scope.
    """
    description = scope_info.optionable_cls.get_description() if scope_info.optionable_cls else None
    return self.get_parser(scope_info.scope).format_help(scope_info.scope, description,
                                                         self._help_request.advanced)
