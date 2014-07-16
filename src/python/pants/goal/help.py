# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from optparse import OptionParser

from pants.base.build_environment import pants_release
from pants.goal.option_helpers import add_global_options
from pants.goal.phase import Phase


def print_help(goals=None):
  if goals:
    for goal in goals:
      phase = Phase(goal)
      if not phase.goals():
        print('\nUnknown goal: %s' % goal)
      else:
        parser = OptionParser(add_help_option=False)
        phase.setup_parser(parser, [], [phase])
        print('\n%s: %s' % (phase.name, phase.description))
        _print_flags(parser, phase.name)
  else:
    print(pants_release())
    print('\nUsage:')
    print('  ./pants goal [option ...] [goal ...] [target...]  Attempt the specified goals.')
    print('  ./pants goal help                                 Get help.')
    print('  ./pants goal help [goal]                          Get help for the specified goal.')
    print('  ./pants goal goals                                List all installed goals.')
    print('')
    print('  [target] accepts two special forms:')
    print('    dir:  to include all targets in the specified directory.')
    print('    dir:: to include all targets found recursively under the directory.')

    print('\nFriendly docs:\n  http://pantsbuild.github.io/')

    _print_global_flags()


# Note: we create temporary OptionParsers just for formatting the flag help strings.
# Note that we don't use parser's full help message. This is slightly hacky, but
# allows us much better control over the output. And we'll be getting off optparse
# soon and onto our own cmd-line parser anyway.

def _print_global_flags():
  parser = OptionParser(add_help_option=False)
  add_global_options(parser)
  _print_flags(parser, 'Global')


def _print_flags(parser, main_heading):
  parser.formatter.store_option_strings(parser)

  opt_strs = []
  def add_opt_strs(opts, heading):
    if opts:
      opt_strs.append('\n%s options:' % heading)
      for opt in opts:
        for s in parser.formatter.format_option(opt).splitlines():
          opt_strs.append('  ' + s)

  add_opt_strs(parser.option_list, main_heading)
  for opt_group in parser.option_groups:
    add_opt_strs(opt_group.option_list, opt_group.title)

  if opt_strs:
    for opt_str in opt_strs:
      print(opt_str)
