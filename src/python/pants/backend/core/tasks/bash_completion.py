# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from collections import defaultdict

from pkg_resources import resource_string

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.exceptions import TaskError
from pants.base.generator import Generator
from pants.goal.goal import Goal
from pants.option.arg_splitter import GLOBAL_SCOPE


class BashCompletionTask(ConsoleTask):
  """Generate a Bash shell script that teaches Bash how to autocomplete pants command lines."""

  @staticmethod
  def expand_option_strings(option_strings):
    """Expand a list of option string templates into all represented option strings.

    Optional portions of an option string are marked in brackets. For example, '--[no-]some-bool-option'
    expands to '--some-bool-option' and '--no-some-bool-option'.
    """
    result = set()
    for option_string in option_strings:
      if '[' in option_string:
        result.add(re.sub(r'\[.*?\]', '', option_string))
        result.add(option_string.replace('[', '').replace(']', ''))
      else:
        result.add(option_string)
    return result

  # TODO: This method should use a custom registration function to obtain the options.
  @staticmethod
  def option_strings_from_parser(parser):
    """Return a set of all of the option strings supported by an options parser."""
    option_strings = set()
    for action in parser.walk_actions():
      for option_string in action.option_strings:
        option_strings.add(option_string)
    return option_strings

  @staticmethod
  def bash_scope_name(scope):
    return scope.replace('-', '_').replace('.', '_')

  @staticmethod
  def generate_scoped_option_strings(option_strings, scope):
    escaped_scope = scope.replace('.', '-')

    result = set()

    for option_string in option_strings:
      if option_string[:2] == '--':
        if option_string[2:7] == '[no-]':
          result.add('--{scope}-{arg}'.format(scope=escaped_scope, arg=option_string[7:]))
          result.add('--no-{scope}-{arg}'.format(scope=escaped_scope, arg=option_string[7:]))
        else:
          result.add('--{scope}-{arg}'.format(scope=escaped_scope, arg=option_string[2:]))

    return result

  @staticmethod
  def parse_all_tasks_and_help(self):
    """Loads all goals, and mines the options & help text for each one.

    Returns: a set of all_scopes, options_text string, a set of all option strings
    """
    options = self.context.options

    goals = Goal.all()
    all_scopes = set()
    option_strings_by_scope = defaultdict(set)

    def record(scope, option_strings):
      option_strings_by_scope[scope] |= self.expand_option_strings(option_strings)

    for goal in goals:
      for scope in goal.known_scopes():
        all_scopes.add(scope)

        option_strings_for_scope = set()
        parser = options.get_parser(scope).get_help_argparser()
        if parser:
          option_strings = self.option_strings_from_parser(parser) if parser else set()
          record(scope, option_strings)

          scoped_option_strings = self.generate_scoped_option_strings(option_strings, scope)
          record(scope, scoped_option_strings)

          if '.' in scope:
            outer_scope = scope.partition('.')[0]
            record(outer_scope, scoped_option_strings)

    # TODO: This does not currently handle subsystem-specific options.
    global_argparser = options.get_parser(GLOBAL_SCOPE).get_help_argparser()
    global_option_strings = self.option_strings_from_parser(global_argparser) or []
    global_option_strings_set = self.expand_option_strings(global_option_strings)

    options_text = '\n'.join([
      "__pants_options_for_{}='{}'".format(self.bash_scope_name(scope), ' '.join(sorted(list(option_strings))))
      for scope, option_strings in sorted(option_strings_by_scope.items(), key=lambda x: x[0])
    ])

    return all_scopes, options_text, global_option_strings_set

  def console_output(self, targets):
    if targets:
      raise TaskError('This task does not accept any target addresses.')

    (all_scopes, options_text, global_option_strings_set) = self.parse_all_tasks_and_help(self)

    generator = Generator(
      resource_string(__name__, os.path.join('templates', 'bash_completion', 'autocomplete.sh.mustache')),
      scopes_text=' '.join(sorted(list(all_scopes))),
      options_text=options_text,
      global_options=' '.join(sorted(list(global_option_strings_set)))
    )

    for line in generator.render().split('\n'):
      yield line
