# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import namedtuple
import sys

from twitter.common.collections import OrderedSet


GLOBAL_SCOPE = ''


class ArgSplitterError(Exception):
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


class ArgSplitter(object):
  """Splits a command-line into scoped sets of flags, and a set of targets.

  Recognizes, e.g.:

  ./pants goal -x compile --foo compile.java -y target1 target2
  ./pants -x compile --foo compile.java -y -- target1 target2
  ./pants -x compile target1 target2 --compile-java-flag
  ./pants -x --compile-java-flag compile target1 target2

  Handles help flags (-h, --help and the scope 'help') specially.
  """
  _HELP_FLAGS = ('-h', '--help')

  def __init__(self, known_scopes):
    self._known_scopes = set(known_scopes + ['help'])
    self._unconsumed_args = []  # In reverse order, for efficient popping off the end.
    self._is_help = False  # True if the user asked for help.

    # For historical reasons we allow --scope-flag-name anywhere on the cmd line,
    # as an alternative to ... scope --flag-name. This makes the transition to
    # the new options system easier, as old-style flags will still work.

    # Check for prefixes in reverse order, so we match the longest prefix first.
    self._known_scoping_prefixes = [('{0}-'.format(scope.replace('.', '-')), scope)
                                    for scope in filter(None, sorted(self._known_scopes, reverse=True))]

  @property
  def is_help(self):
    return self._is_help

  def split_args(self, args=None):
    """Split the specified arg list (or sys.argv if unspecified).

    args[0] is ignored.

    Returns a SplitArgs tuple.
    """
    goals = OrderedSet()
    scope_to_flags = {}

    def add_scope(s):
      # Force the scope to appear, even if empty.
      if s not in scope_to_flags:
        scope_to_flags[s] = []

    targets = []
    passthru = []
    passthru_owner = None

    self._unconsumed_args = list(reversed(sys.argv if args is None else args))
    # In regular use the first token is the binary name, so skip it. However tests may
    # pass just a list of flags, so don't skip it in that case.
    if not self._at_flag() and self._unconsumed_args:
      self._unconsumed_args.pop()
    if self._unconsumed_args and self._unconsumed_args[-1] == 'goal':
      # TODO: Temporary warning. Eventually specifying 'goal' will be an error.
      print("WARNING: Specifying 'goal' explicitly is no longer necessary, and deprecated.",
            file=sys.stderr)
      self._unconsumed_args.pop()

    def assign_flag_to_scope(flag, default_scope):
      flag_scope, descoped_flag = self._descope_flag(flag, default_scope=default_scope)
      if flag_scope not in scope_to_flags:
        scope_to_flags[flag_scope] = []
      scope_to_flags[flag_scope].append(descoped_flag)

    global_flags = self._consume_flags()
    add_scope(GLOBAL_SCOPE)
    for flag in global_flags:
      assign_flag_to_scope(flag, GLOBAL_SCOPE)
    scope, flags = self._consume_scope()
    while scope:
      if scope.lower() == 'help':
        self._is_help = True
      else:
        add_scope(scope)
        goals.add(scope.partition('.')[0])
        passthru_owner = scope
        for flag in flags:
          assign_flag_to_scope(flag, scope)
      scope, flags = self._consume_scope()

    while self._unconsumed_args and not self._at_double_dash():
      arg = self._unconsumed_args.pop()
      if arg.startswith(b'-'):
        # We assume any args here are in global scope.
        if arg in self._HELP_FLAGS:
          self._is_help = True
        else:
          assign_flag_to_scope(arg, GLOBAL_SCOPE)
      else:
        targets.append(arg)

    if self._at_double_dash():
      self._unconsumed_args.pop()
      passthru = list(reversed(self._unconsumed_args))

    if not goals:
      self._is_help = True
    return SplitArgs(goals, scope_to_flags, targets, passthru, passthru_owner if passthru else None)

  def _consume_scope(self):
    """Returns a pair (scope, list of flags encountered in that scope).

    Note that the flag may be explicitly scoped, and therefore not actually belong to this scope.

    For example, in:

    ./pants --compile-java-partition-size-hint=100 compile <target>

    --compile-java-partition-size-hint should be treated as if it were --partition-size-hint=100
    in the compile.java scope.
    """
    if not self._at_scope():
      return None, []
    scope = self._unconsumed_args.pop()
    flags = self._consume_flags()
    return scope, flags

  def _consume_flags(self):
    """Read flags until we encounter the first token that isn't a flag."""
    flags = []
    while self._at_flag():
      flag = self._unconsumed_args.pop()
      if flag in self._HELP_FLAGS:
        self._is_help = True
      else:
        flags.append(flag)
    return flags

  def _descope_flag(self, flag, default_scope):
    """If the flag is prefixed by its scope, in the old style, extract the scope.

    Otherwise assume it belongs to default_scope.

    returns a pair (scope, flag).
    """
    for scope_prefix, scope in self._known_scoping_prefixes:
      for flag_prefix in ['--', '--no-']:
        prefix = flag_prefix + scope_prefix
        if flag.startswith(prefix):
          return scope, flag_prefix + flag[len(prefix):]
    return default_scope, flag

  def _at_flag(self):
    return (self._unconsumed_args and
            self._unconsumed_args[-1].startswith(b'-') and
            not self._at_double_dash())

  def _at_scope(self):
    return self._unconsumed_args and self._unconsumed_args[-1] in self._known_scopes

  def _at_double_dash(self):
    return self._unconsumed_args and self._unconsumed_args[-1] == b'--'
