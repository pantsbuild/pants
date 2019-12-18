# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from typing import Optional, cast

from typing_extensions import Literal

from pants.base.build_environment import pants_release, pants_version
from pants.goal.goal import Goal
from pants.help.help_formatter import HelpFormatter
from pants.help.scope_info_iterator import ScopeInfoIterator
from pants.option.arg_splitter import (
  GoalsHelp,
  HelpRequest,
  NoGoalHelp,
  OptionsHelp,
  UnknownGoalHelp,
  VersionHelp,
)
from pants.option.options import Options
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo


class HelpPrinter:
  """Prints help to the console."""

  def __init__(self, options: Options, *, help_request: Optional[HelpRequest] = None) -> None:
    self._options = options
    self._help_request = help_request or self._options.help_request

  @property
  def bin_name(self) -> str:
    return cast(str, self._options.for_global_scope().pants_bin_name)

  def print_help(self) -> Literal[0, 1]:
    """Print help to the console."""
    def print_hint() -> None:
      print(f'Use `{self.bin_name} goals` to list goals.')
      print(f'Use `{self.bin_name} help` to get help.')

    if isinstance(self._help_request, VersionHelp):
      print(pants_version())
    elif isinstance(self._help_request, OptionsHelp):
      self._print_options_help()
    elif isinstance(self._help_request, GoalsHelp):
      self._print_goals_help()
    elif isinstance(self._help_request, UnknownGoalHelp):
      print('Unknown goals: {}'.format(', '.join(self._help_request.unknown_goals)))
      print_hint()
      return 1
    elif isinstance(self._help_request, NoGoalHelp):
      print('No goals specified.')
      print_hint()
      return 1
    return 0

  def _print_goals_help(self):
    print(f'\nUse `{self.bin_name} help $goal` to get help for a particular goal.\n')
    global_options = self._options.for_global_scope()
    goal_descriptions = {}
    if global_options.v2:
      for scope_info in self._options.known_scope_to_info.values():
        if scope_info.category == ScopeInfo.GOAL:
          description = scope_info.description or "<no description>"
          goal_descriptions[scope_info.scope] = description
    if global_options.v1:
      goal_descriptions.update({goal.name: goal.description_first_line
                                for goal in Goal.all()
                                if goal.description})

    max_width = max(len(name) for name in goal_descriptions.keys()) if goal_descriptions else 0
    for name, description in sorted(goal_descriptions.items()):
      print('  {}: {}'.format(name.rjust(max_width), description))
    print()

  def _print_options_help(self):
    """Print a help screen.

    Assumes that self._help_request is an instance of OptionsHelp.

    Note: Ony useful if called after options have been registered.
    """
    show_all_help = self._help_request.all_scopes
    if show_all_help:
      help_scopes = list(self._options.known_scope_to_info.keys())
    else:
      # The scopes explicitly mentioned by the user on the cmd line.
      help_scopes = set(self._options.scope_to_flags.keys()) - {GLOBAL_SCOPE}

    scope_infos = list(ScopeInfoIterator(self._options.known_scope_to_info).iterate(help_scopes))
    if scope_infos:
      for scope_info in scope_infos:
        help_str = self._format_help(scope_info)
        if help_str:
          print(help_str)
      return
    else:
      print(pants_release())
      print('\nUsage:')
      print(f'  {self.bin_name} [option ...] [goal ...] [target...]  Attempt the specified goals.')
      print(f'  {self.bin_name} help                                 Get help.')
      print(f'  {self.bin_name} help [goal]                          Get help for a goal.')
      print(f'  {self.bin_name} help-advanced [goal]                 Get help for a goal\'s advanced options.')
      print(f'  {self.bin_name} help-all                             Get help for all goals.')
      print(f'  {self.bin_name} goals                                List all installed goals.')
      print('')
      print('  [target] accepts two special forms:')
      print('    dir:  to include all targets in the specified directory.')
      print('    dir:: to include all targets found recursively under the directory.')
      print('\nFriendly docs:\n  http://pantsbuild.org/')

      print(self._format_help(ScopeInfo(GLOBAL_SCOPE, ScopeInfo.GLOBAL)))

  def _format_help(self, scope_info):
    """Return a help message for the options registered on this object.

    Assumes that self._help_request is an instance of OptionsHelp.

    :param scope_info: Scope of the options.
    """
    scope = scope_info.scope
    description = scope_info.description
    help_formatter = HelpFormatter(
      scope=scope,
      show_recursive=self._help_request.advanced,
      show_advanced=self._help_request.advanced,
      color=sys.stdout.isatty(),
    )
    formatted_lines = help_formatter.format_options(
      scope, description, self._options.get_parser(scope).option_registrations_iter()
    )
    return '\n'.join(formatted_lines)
