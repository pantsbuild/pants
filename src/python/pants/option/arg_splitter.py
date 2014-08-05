# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import sys


GLOBAL_SCOPE = ''


class ArgSplitterError(Exception):
  pass


class ArgSplitter(object):
  """Splits a command-line into scoped sets of flags, and a set of targets.

  Recognizes, e.g.:

  ./pants goal -x compile --foo compile.java -y target1 target2
  ./pants -x compile --foo compile.java -y -- target1 target2

  Handles help flags (-h, --help and the scope 'help') specially.
  """
  def __init__(self, known_scopes):
    self._known_scopes = set(known_scopes + ['help'])
    self._unconsumed_args = []  # In reverse order, for efficient popping off the end.
    self._is_help = False  # True if the user asked for help.

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
    scope_to_flags = {}
    targets = []

    self._unconsumed_args = list(reversed(sys.argv if args is None else args))[:-1]
    if self._unconsumed_args and self._unconsumed_args[-1] == 'goal':
      # TODO: Temporary warning. Eventually specifying 'goal' will be an error.
      print("WARNING: Specifying the 'goal' command explicitly is superfluous and deprecated.")
      self._unconsumed_args.pop()
    # The 'new' command is a temporary hack during migration.
    if self._unconsumed_args and self._unconsumed_args[-1] == 'new':
      self._unconsumed_args.pop()

    global_flags = self._consume_flags()
    scope_to_flags[GLOBAL_SCOPE] = global_flags
    scope, flags = self._consume_scope()
    while scope:
      scope_to_flags[scope] = flags
      scope, flags = self._consume_scope()

    if self._at_double_dash():
      self._unconsumed_args.pop()

    target = self._consume_target()
    while target:
      targets.append(target)
      target = self._consume_target()

    # We parse the word 'help' as a scope, but it's not a real one, so ignore it.
    scope_to_flags.pop('help', None)
    return scope_to_flags, targets

  def _consume_scope(self):
    if not self._at_scope():
      return None, []
    scope = self._unconsumed_args.pop()
    if scope.lower() == 'help':
      self._is_help = True
    flags = self._consume_flags()
    return scope, flags

  def _consume_flags(self):
    flags = []
    while self._at_flag():
      flag = self._unconsumed_args.pop()
      if flag in ('-h', '--help'):
        self._is_help = True
      else:
        flags.append(flag)
    return flags

  def _consume_target(self):
    if not self._unconsumed_args:
      return None
    target = self._unconsumed_args.pop()
    if target.startswith(b'-'):  # Special-case check for what may be a common error.
      raise ArgSplitterError('Invalid target name: %s. Flags cannot appear here.' % target)
    return target

  def _at_flag(self):
    return (self._unconsumed_args and
            self._unconsumed_args[-1].startswith(b'-') and
            not self._at_double_dash())

  def _at_scope(self):
    return self._unconsumed_args and self._unconsumed_args[-1] in self._known_scopes

  def _at_double_dash(self):
    return self._unconsumed_args and self._unconsumed_args[-1] == b'--'
