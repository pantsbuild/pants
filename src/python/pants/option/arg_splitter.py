# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys
from collections import namedtuple

from twitter.common.collections import OrderedSet

from pants.option.scope import ScopeInfo
from pants.util.meta import AbstractClass


GLOBAL_SCOPE = ''


class ArgSplitterError(Exception):
  """ArgSplitter Exception subclass"""
  pass


class SplitArgs(namedtuple('SplitArgs',
                           ['goals', 'scope_to_flags', 'targets', 'passthru', 'passthru_owner'])):
  """The result of splitting args.

  goals: A list of explicitly specified goals.
  scope_to_flags: An ordered map from scope name to the list of flags belonging to that scope.
                  The global scope is specified as an empty string.
                  Keys are in the order encountered in the args.
  targets: A list of target specs.
  passthru: Any remaining args specified after a -- separator.
  passthru_owner: The scope specified last on the command line, if any. None otherwise.
  """
  pass


class HelpRequest(AbstractClass):
  """Represents an implicit or explicit request for help by the user."""
  pass


class OptionsHelp(HelpRequest):
  """User requested help."""

  def __init__(self, advanced=False, all_scopes=False):
    """The user requested help for cmd-line options.

    :param advanced: Did the user ask for advanced help (e.g., using --help-advanced).
    :param all_scopes: Did the user ask for help for all goals and tasks (e.g., using --help-all).
    """
    super(OptionsHelp, self).__init__()
    self.advanced = advanced
    self.all_scopes = all_scopes


class UnknownGoalHelp(HelpRequest):
  """The user specified an unknown goal (or task)."""

  def __init__(self, unknown_goals):
    """Handle unknown goals specifed by user.

    :param unknown_goals: goals provided by the user that we were unable to match
    """
    super(UnknownGoalHelp, self).__init__()
    self.unknown_goals = unknown_goals


class NoGoalHelp(HelpRequest):
  """The user specified no goals."""
  pass


class ArgSplitter(object):
  """Splits a command-line into scoped sets of flags, and a set of targets.

  Recognizes, e.g.:

  ./pants goal -x compile --foo compile.java -y target1 target2
  ./pants -x compile --foo compile.java -y -- target1 target2
  ./pants -x compile target1 target2 --compile-java-flag
  ./pants -x --compile-java-flag compile target1 target2

  Handles help and version args specially.
  """
  _HELP_BASIC_ARGS = ('-h', '--help', 'help')
  _HELP_ADVANCED_ARGS = ('--help-advanced', 'help-advanced')
  _HELP_ALL_SCOPES_ARGS = ('--help-all', 'help-all')
  _HELP_ARGS = _HELP_BASIC_ARGS + _HELP_ADVANCED_ARGS + _HELP_ALL_SCOPES_ARGS

  def __init__(self, known_scope_infos):
    """Handle splitting command line args into sets of scoped flags and targets

    Arguments are stored in a reverse order in self._unconsummed args in order
    to be able to efficiently pop arguments off.
    """
    # Note: For convenience, and for historical reasons, we allow --scope-flag-name anywhere on the
    #   cmd line, as an alternative to ... scope --flag-name.
    #
    # TODO: Get rid of our reliance on known scopes here. We don't really need it now
    #   that we heuristically identify target specs based on it containing /, : or being
    #   a top-level directory.
    self._known_scope_infos = known_scope_infos
    self._known_scopes = (set([si.scope for si in known_scope_infos]) |
                          {'help', 'help-advanced', 'help-all'})

    self._goals = OrderedSet()
    self._passthru = []
    self._scope_to_flags = {}
    self._targets = []
    self._unconsumed_args = []  # In reverse order, for efficient popping off the end.
    self._unknown_scopes = []
    self.help_request = None  # Will be set if we encounter any help flags.

    # We check for prefixes in reverse order, so we match the longest prefix first.
    sorted_scope_infos = sorted(filter(lambda si: si.scope, self._known_scope_infos),
                                key=lambda si: si.scope, reverse=True)

    # List of pairs (prefix, ScopeInfo).
    self._known_scoping_prefixes = [('{0}-'.format(si.scope.replace('.', '-')), si)
                                    for si in sorted_scope_infos]

  def _check_for_help_request(self, arg):
    """Check if arg is help request or not"""
    return arg in self._HELP_ARGS

  def _setup_help_request(self, arg):
    """Setup help request to have an instance of OptionsHelp"""

    def is_advanced(arg):
      return self.help_request.advanced or arg in self._HELP_ADVANCED_ARGS

    def is_all_scopes(arg):
      return self.help_request.all_scopes or arg in self._HELP_ALL_SCOPES_ARGS

    # Setup base instance if it doesn't exist
    if not self.help_request:
      self.help_request = OptionsHelp()
    # Now see if we need to enhance it.
    if isinstance(self.help_request, OptionsHelp):
      advanced = is_advanced(arg)
      all_scopes = is_all_scopes(arg)
      self.help_request = OptionsHelp(advanced=advanced, all_scopes=all_scopes)

  def _initialize_scope(self, scope):
    """Create empty scope if not in scope to flags"""
    if scope not in self._scope_to_flags:
      self._scope_to_flags[scope] = []

  def _assign_flag_to_scope(self, flag, default_scope):
    """Assign flag to the scope specified"""
    flag_scope, descoped_flag = self._descope_flag(flag, default_scope=default_scope)
    if flag_scope not in self._scope_to_flags:
      self._scope_to_flags[flag_scope] = []
    self._scope_to_flags[flag_scope].append(descoped_flag)

  def _assign_flags_to_scope(self, flags, scope):
    """Assign all flags to the scope specified"""
    for flag in flags:
      self._assign_flag_to_scope(flag, scope)

  def _consume_scoped_args(self):
    """Process with scoped args"""
    passthru_owner = None
    for scope, flags in self._consume_scope():
      if not self._check_for_help_request(scope.lower()):
        self._initialize_scope(scope)
        self._goals.add(scope.partition('.')[0])
        passthru_owner = scope
        self._assign_flags_to_scope(flags, scope)
      else:
        self._setup_help_request(scope.lower())
    return passthru_owner

  def _consume_global_args(self):
    "Process global args and stop"
    while self._unconsumed_args and not self._at_double_dash():
      arg = self._next_unconsumed
      if arg.startswith(b'-'):
        if self._check_for_help_request(arg):
          self._setup_help_request(arg)
        else:
          self._assign_flag_to_scope(arg, GLOBAL_SCOPE)  # We assume args in global scope
      elif os.path.sep in arg or ':' in arg or os.path.isdir(arg):
        self._targets.append(arg)
      elif arg not in self._known_scopes:
        self._unknown_scopes.append(arg)

  def split_args(self, args=None):
    """Split the specified arg list (or sys.argv if unspecified).

    args[0] is ignored.

    Returns a SplitArgs tuple.
    """

    self._unconsumed_args = list(reversed(sys.argv if args is None else args))
    # In regular use the first token is the binary name, so skip it. However tests may
    # pass just a list of flags, so don't skip it in that case.
    if not self._at_flag() and self._unconsumed_args:
      self._next_unconsumed
    if self._unconsumed_args and self._unconsumed_args[-1] == 'goal':
      # TODO: Temporary warning. Eventually specifying 'goal' will be an error.
      print("WARNING: Specifying 'goal' explicitly is no longer necessary, and deprecated.",
            file=sys.stderr)
      self._next_unconsumed

    global_flags = self._consume_flags()

    self._initialize_scope(GLOBAL_SCOPE)
    self._assign_flags_to_scope(global_flags, GLOBAL_SCOPE)
    passthru_owner = self._consume_scoped_args()
    self._consume_global_args()

    # Double dash pass through to underlying command.
    if self._at_double_dash():
      self._next_unconsumed
      self._passthru = list(reversed(self._unconsumed_args))

    # Set appropriate help request if needed.
    if self._unknown_scopes:
      self.help_request = UnknownGoalHelp(self._unknown_scopes)

    if not self._goals and not self.help_request:
      self.help_request = NoGoalHelp()

    passthru_owner = passthru_owner if self._passthru else None
    return SplitArgs(
      self._goals,
      self._scope_to_flags,
      self._targets,
      self._passthru,
      passthru_owner
    )

  def _consume_scope(self):
    """Returns a pair (scope, list of flags encountered in that scope).

    Note that the flag may be explicitly scoped, and therefore not actually belong to this scope.

    For example, in:

    ./pants --compile-java-partition-size-hint=100 compile <target>

    --compile-java-partition-size-hint should be treated as if it were --partition-size-hint=100
    in the compile.java scope.
    """
    while self._at_scope():
      scope = self._next_unconsumed
      if not scope:
        return
      else:
        yield scope, self._consume_flags()

  def _consume_flags(self):
    """Read flags until we encounter the first token that isn't a flag."""
    flags = []
    while self._at_flag():
      flag = self._next_unconsumed
      if self._check_for_help_request(flag):
        self._setup_help_request(flag)
      else:
        flags.append(flag)
    return flags

  def _descope_flag(self, flag, default_scope):
    """If the flag is prefixed by its scope, in the old style, extract the scope.

    Otherwise assume it belongs to default_scope.

    returns a pair (scope, flag).
    """
    for scope_prefix, scope_info in self._known_scoping_prefixes:
      for flag_prefix in ['--', '--no-']:
        prefix = flag_prefix + scope_prefix
        if flag.startswith(prefix):
          scope = scope_info.scope
          if scope_info.category == ScopeInfo.SUBSYSTEM and default_scope != GLOBAL_SCOPE:
            # We allow goal.task --subsystem-foo to refer to the task-level subsystem instance,
            # i.e., as if qualified by --subsystem-goal-task-foo.
            # Note that this means that we can't set a task option on the cmd-line if its
            # name happens to start with a subsystem scope.
            # TODO: Either fix this or at least detect such options and warn.
            task_subsystem_scope = '{}.{}'.format(scope_info.scope, default_scope)
            if task_subsystem_scope in self._known_scopes:  # Such a task subsystem actually exists.
              scope = task_subsystem_scope
          return scope, flag_prefix + flag[len(prefix):]
    return default_scope, flag

  @property
  def _next_unconsumed(self):
    """Fetch the next unconsumed arg"""
    return self._unconsumed_args.pop()

  @property
  def _peek(self):
    """Safely retrieve the next arg"""
    return self._unconsumed_args[-1] or ''

  def _at_flag(self):
    """Determine if the currently next argument is a flag"""
    return (self._unconsumed_args and self._peek.startswith(b'-') and not self._at_double_dash())

  def _at_scope(self):
    """Determine if the next arg is a scope identifier"""
    return self._unconsumed_args and self._peek in self._known_scopes

  def _at_double_dash(self):
    """Determine if the next arg is a double dash"""
    return self._unconsumed_args and self._peek == b'--'
