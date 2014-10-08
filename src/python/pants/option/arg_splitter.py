# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import sys


GLOBAL_SCOPE = ''


class ArgSplitterError(Exception):
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
  def __init__(self, known_scopes):
    self._known_scopes = set(known_scopes + ['help'])
    self._unconsumed_args = []  # In reverse order, for efficient popping off the end.
    self._is_help = False  # True if the user asked for help.

    # For historical reasons we allow --leaf-scope-flag-name anywhere on the cmd line,
    # as an alternative to ... leaf.scope --flag-name. This makes the transition to
    # the new options system easier, as old-style flags will still work.
    self._known_scoping_prefixes = {}

    # Note: This algorithm for finding the lead scopes relies on the fact that enclosing
    # scopes are earlier than enclosed scopes in the list.
    leaf_scopes = set()
    for scope in known_scopes:
      if scope:
        outer_scope, _, _ = scope.rpartition('.')
        if outer_scope in leaf_scopes:
          leaf_scopes.discard(outer_scope)
        leaf_scopes.add(scope)
    for scope in leaf_scopes:
      self._known_scoping_prefixes['{0}-'.format(scope.replace('.', '-'))] = scope

  @property
  def is_help(self):
    return self._is_help

  def split_args(self, args=None):
    """Split the specified arg list (or sys.argv if unspecified).

    args[0] is ignored.

    Returns a pair scope_to_flags, targets where scope_to_flags is a map from scope name
    to the list of flags belonging to that scope, and targets are a list of targets. The
    global scope is designated by an empty string.
    """
    scope_to_flags = defaultdict(list)
    targets = []

    self._unconsumed_args = list(reversed(sys.argv if args is None else args))
    # In regular use the first token is the binary name, so skip it. However tests may
    # pass just a list of flags, so don't skip it in that case.
    if not self._at_flag() and self._unconsumed_args:
      self._unconsumed_args.pop()
    if self._unconsumed_args and self._unconsumed_args[-1] == 'goal':
      # TODO: Temporary warning. Eventually specifying 'goal' will be an error.
      # Turned off for now because it's annoying. Will turn back on at some point during migration.
      #print("WARNING: Specifying the 'goal' command explicitly is superfluous and deprecated.",
      #      file=sys.stderr)
      self._unconsumed_args.pop()

    def assign_flag_to_scope(flag, default_scope):
      flag_scope, descoped_flag = self._descope_flag(flag, default_scope=default_scope)
      scope_to_flags[flag_scope].append(descoped_flag)

    global_flags = self._consume_flags()
    scope_to_flags[GLOBAL_SCOPE].extend([])  # Force the scope to appear, even if empty.
    for flag in global_flags:
      assign_flag_to_scope(flag, GLOBAL_SCOPE)
    scope, flags = self._consume_scope()
    while scope:
      scope_to_flags[scope].extend([])  # Force the scope to appear, even if empty.
      for flag in flags:
        assign_flag_to_scope(flag, scope)
      scope, flags = self._consume_scope()

    if self._at_double_dash():
      self._unconsumed_args.pop()

    while self._unconsumed_args:
      arg = self._unconsumed_args.pop()
      if arg.startswith(b'-'):
        # During migration we allow flags here, and assume they are in global scope.
        # TODO(benjy): Should we allow this even after migration?
        assign_flag_to_scope(arg, GLOBAL_SCOPE)
      else:
        targets.append(arg)

    # We parse the word 'help' as a scope, but it's not a real one, so ignore it.
    scope_to_flags.pop('help', None)
    return scope_to_flags, targets

  def _consume_scope(self):
    """Returns a pair (scope, list of flags encountered in that scope).

    Each entry in the list is a pair (scope, flag) in case the flag was explicitly
    scoped in the old style, and therefore may not actually belong to this scope.

    For example, in:

    ./pants --compile-java-partition-size-hint=100 compile <target>

    --compile-java-partition-size-hint should be treated as if it were --partition-size-hint=100
    in the compile.java scope.  This will make migration from old- to new-style flags much easier.
    In fact, we may want to allow this even post-migration, for users that prefer it.
    """
    if not self._at_scope():
      return None, []
    scope = self._unconsumed_args.pop()
    if scope.lower() == 'help':
      self._is_help = True
    flags = self._consume_flags()
    return scope, flags

  def _consume_flags(self):
    """Read flags until we encounter the first token that isn't a flag."""
    flags = []
    while self._at_flag():
      flag = self._unconsumed_args.pop()
      if flag in ('-h', '--help'):
        self._is_help = True
      else:
        flags.append(flag)
    return flags

  def _descope_flag(self, flag, default_scope):
    """If the flag is prefixed by its scope, in the old style, extract the scope.

    Otherwise assume it belongs to default_scope.

    returns a pair (scope, flag).
    """
    for scope_prefix, scope in self._known_scoping_prefixes.iteritems():
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
