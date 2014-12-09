# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import copy
import sys

from pants.base.build_environment import pants_release
from pants.goal.goal import Goal
from pants.option import custom_types
from pants.option.arg_splitter import ArgSplitter, GLOBAL_SCOPE
from pants.option.option_value_container import OptionValueContainer
from pants.option.parser_hierarchy import ParserHierarchy


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
  GLOBAL_SCOPE = GLOBAL_SCOPE

  # Custom option types. You can specify these with type= when registering options.

  # A dict-typed option.
  dict = staticmethod(custom_types.dict_type)

  # A list-typed option. Note that this is different than an action='append' option:
  # An append option will append the cmd-line values to the default. A list-typed option
  # will replace the default with the cmd-line value.
  list = staticmethod(custom_types.list_type)


  def __init__(self, env, config, known_scopes, args=sys.argv, bootstrap_option_values=None):
    """Create an Options instance.

    :param env: a dict of environment variables.
    :param config: data from a config file (must support config.get[list](section, name, default=)).
    :param known_scopes: a list of all possible scopes that may be encountered.
    :param args: a list of cmd-line args.
    :param bootstrap_option_values: An optional namespace containing the values of bootstrap
           options. We can use these values when registering other options.
    """
    splitter = ArgSplitter(known_scopes)
    self._goals, self._scope_to_flags, self._target_specs, self._passthru, self._passthru_owner = \
      splitter.split_args(args)
    self._is_help = splitter.is_help
    self._parser_hierarchy = ParserHierarchy(env, config, known_scopes)
    self._values_by_scope = {}  # Arg values, parsed per-scope on demand.
    self._bootstrap_option_values = bootstrap_option_values

  @property
  def target_specs(self):
    """The targets to operate on."""
    return self._target_specs

  @property
  def goals(self):
    """The requested goals, in the order specified on the cmd line."""
    return self._goals

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

  @property
  def is_help(self):
    """Whether the command line indicates a request for help."""
    return self._is_help

  def format_global_help(self):
    """Generate a help message for global options."""
    return self.get_global_parser().format_help()

  def format_help(self, scope):
    """Generate a help message for options at the specified scope."""
    return self.get_parser(scope).format_help()

  def register(self, scope, *args, **kwargs):
    """Register an option in the given scope, using argparse params."""
    self.get_parser(scope).register(*args, **kwargs)

  def register_global(self, *args, **kwargs):
    """Register an option in the global scope, using argparse params."""
    self.register(GLOBAL_SCOPE, *args, **kwargs)

  def get_parser(self, scope):
    """Returns the parser for the given scope, so code can register on it directly."""
    return self._parser_hierarchy.get_parser_by_scope(scope)

  def get_global_parser(self):
    """Returns the parser for the global scope, so code can register on it directly."""
    return self.get_parser(GLOBAL_SCOPE)

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

  def bootstrap_option_values(self):
    """Return the option values for bootstrap options.

    General code can also access these values in the global scope.  But option registration code
    cannot, hence this special-casing of this small set of options.
    """
    return self._bootstrap_option_values

  def for_global_scope(self):
    """Return the option values for the global scope."""
    return self.for_scope(GLOBAL_SCOPE)

  def print_help(self, msg=None, goals=None):
    """Print a help screen, followed by an optional message.

    Note: Ony useful if called after options have been registered.
    """
    def _maybe_help(scope):
      s = self.format_help(scope)
      if s != '':  # Avoid printing scope name for scope with empty options.
        print(scope)
        for line in s.split('\n'):
          if line != '':  # Avoid superfluous blank lines for empty strings.
            print('  {0}'.format(line))

    goals = goals or self.goals
    if goals:
      for goal_name in goals:
        goal = Goal.by_name(goal_name)
        if not goal.ordered_task_names():
          print('\nUnknown goal: %s' % goal_name)
        else:
          print('\n{0}: {1}\n'.format(goal.name, goal.description))
          for scope in goal.known_scopes():
            _maybe_help(scope)
    else:
      print(pants_release())
      print('\nUsage:')
      print('  ./pants [option ...] [goal ...] [target...]  Attempt the specified goals.')
      print('  ./pants help                                 Get help.')
      print('  ./pants help [goal]                          Get help for the specified goal.')
      print('  ./pants goal goals                           List all installed goals.')
      print('')
      print('  [target] accepts two special forms:')
      print('    dir:  to include all targets in the specified directory.')
      print('    dir:: to include all targets found recursively under the directory.')

      print('\nFriendly docs:\n  http://pantsbuild.github.io/')

      print('\nGlobal options:')
      print(self.format_global_help())

    if msg is not None:
      print(msg)
