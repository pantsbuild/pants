# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import argparse


class PantsHelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
  """A custom argparse help formatter subclass.

  Squelches extraneous text, such as usage messages and section headers, because
  we format those ourselves.  Leaves just the actual flag help.
  """

  def __init__(self, show_advanced_output, *args, **kwargs):
    super(PantsHelpFormatter, self).__init__(*args, **kwargs)
    self._in_advanced_section = False
    self._pants_scope = None
    self._show_advanced_output = show_advanced_output

  def add_usage(self, usage, actions, groups, prefix=None):
    pass

  def add_text(self, text):
    pass

  def start_section(self, heading):
    # The title of the argument group containing advanced features starts with an '*'
    if heading[:1] == '*':
      self._in_advanced_section = True
      self._pants_scope = heading[1:]
    else:
      self._pants_scope = heading

  def end_section(self):
    self._in_advanced_section = False

  def _pants_arg_long_format_helper(self, action):
    if self._pants_scope:
      heading = self._pants_scope.replace('.', '-')
      for option_string in action.option_strings:
        if option_string[:2] == '--':
          if option_string[2:7] == '[no-]':
            invert_flag = '[no-]'
            option_flag = option_string[7:]
          else:
            invert_flag = ''
            option_flag = option_string[2:]

          arg_name = action.metavar if action.metavar else action.dest
          arg_value = '' if action.nargs == 0 else '={0}'.format(arg_name)

          return '--{invert_flag}{heading}-{option_flag}{arg_value}\n'.format(
            invert_flag=invert_flag, heading=heading,
            option_flag=option_flag, arg_value=arg_value)

  def add_argument(self, action):
    """Override the stock add_argument() method in HelpFormatter

    Conditionally suppress the advanced options group.
    Also, add the fully-qualified flag to the help output.
    """

    if not self._in_advanced_section or self._show_advanced_output:
      # NB: This uses _add_item() which is a private implementation detail of the
      # ArgParse.HelpFormatter class.  It is subject to change in future releases of argparse.
      if self._in_advanced_section:
        def advanced_prefix_helper():
          return '(ADVANCED)\n'
        self._add_item(advanced_prefix_helper, [])
      self._add_item(self._pants_arg_long_format_helper, [action])
      super(PantsHelpFormatter, self).add_argument(action)


class PantsBasicHelpFormatter(PantsHelpFormatter):
  def __init__(self, *args, **kwargs):
    super(PantsBasicHelpFormatter, self).__init__(False, *args, **kwargs)


class PantsAdvancedHelpFormatter(PantsHelpFormatter):
  def __init__(self, *args, **kwargs):
    super(PantsAdvancedHelpFormatter, self).__init__(True, *args, **kwargs)
