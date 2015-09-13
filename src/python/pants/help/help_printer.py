# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

from pants.base.build_environment import pants_release
from pants.help.help_formatter import HelpFormatter
from pants.option.arg_splitter import GLOBAL_SCOPE, NoGoalHelp, OptionsHelp, UnknownGoalHelp
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.parser_hierarchy import enclosing_scope
from pants.option.scope import ScopeInfo
from pants.subsystem.subsystem_client_mixin import SubsystemClientMixin


class HelpPrinter(object):
  """Prints help to the console."""

  def __init__(self, options):
    self._options = options

  @property
  def _help_request(self):
    return self._options.help_request

  @property
  def _known_scope_to_info(self):
    return self._options.known_scope_to_info

  def print_help(self):
    """Print help to the console."""
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
      help_scopes = set(self._options.scope_to_flags.keys()) - set([GLOBAL_SCOPE])
      # As a user-friendly heuristic, add all task scopes under requested scopes, so that e.g.,
      # `./pants help compile` will show help for compile.java, compile.scala etc.
      # Note that we don't do anything similar for subsystems - that would just create noise by
      # repeating options for every task-specific subsystem instance.
      for scope, info in self._known_scope_to_info.items():
        if info.category == ScopeInfo.TASK:
          outer = enclosing_scope(scope)
          while outer != GLOBAL_SCOPE:
            if outer in help_scopes:
              help_scopes.add(scope)
              break
            outer = enclosing_scope(outer)

    help_scope_infos = [self._known_scope_to_info[s] for s in sorted(help_scopes)]
    if help_scope_infos:
      for scope_info in self._help_subscopes_iter(help_scope_infos):
        description = (scope_info.optionable_cls.get_description() if scope_info.optionable_cls
                       else None)
        help_str = self._format_help(scope_info, description)
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

      print(self._format_help(ScopeInfo(GLOBAL_SCOPE, ScopeInfo.GLOBAL), ''))

  def _help_subscopes_iter(self, scope_infos):
    """Yields the scopes to actually show help for when the user asks for help for scope_info."""
    for scope_info in scope_infos:
      yield scope_info
      # We don't currently subclass GlobalOptionsRegistrar, and I can't think of any reason why
      # we would, but might as well be robust.
      if scope_info.optionable_cls is not None:
        if issubclass(scope_info.optionable_cls, GlobalOptionsRegistrar):
          for scope, info in self._known_scope_to_info.items():
            if info.category == ScopeInfo.SUBSYSTEM and enclosing_scope(scope) == GLOBAL_SCOPE:
              # This is a global subsystem, so show it when asked for global help.
              yield info
        elif issubclass(scope_info.optionable_cls, SubsystemClientMixin):
          def yield_deps(subsystem_client_cls):
            for dep in subsystem_client_cls.subsystem_dependencies_iter():
              if dep.scope != GLOBAL_SCOPE:
                yield self._known_scope_to_info[dep.options_scope()]
                for info in yield_deps(dep.subsystem_cls):
                  yield info
          for info in yield_deps(scope_info.optionable_cls):
            yield info

  def _format_help(self, scope_info, description):
    """Return a help message for the options registered on this object.

    Assumes that self._help_request is an instance of OptionsHelp.

    :param scope_info: Scope of the options.
    :param description: Description of scope.
    """
    scope = scope_info.scope
    show_recursive = self._help_request.advanced
    show_advanced = self._help_request.advanced
    color = sys.stdout.isatty()
    registration_args = self._options.get_parser(scope).registration_args
    help_formatter = HelpFormatter(scope, show_recursive, show_advanced, color)
    return '\n'.join(help_formatter.format_options(scope, description, registration_args))
