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
  def add_usage(self, usage, actions, groups, prefix=None):
    pass

  def add_text(self, text):
    pass

  def start_section(self, heading):
    self._pants_heading = heading
    pass

  def end_section(self):
    pass

  def _pants_arg_long_format_helper(self, action):
    if self._pants_heading:
      heading = self._pants_heading.replace('.', '-')
      for option_string in action.option_strings:
        if option_string[:2] == '--':
          if option_string[2:7] == '[no-]':
            invert_flag = '[no-]'
            option_flag = option_string[7:]
          else:
            invert_flag = ''
            option_flag = option_string[2:]
          return '--{invert_flag}{heading}-{option_flag}\n'.format(
            invert_flag=invert_flag, heading=heading, option_flag=option_flag)

  def add_argument(self, action):
    """
    Add the fully-qualified flag to the help output.
    """
    # NB: This uses _add_item() which is a private implementation detail of the
    # ArgParse.HelpFormatter class.  It is subject to change in future releases of argparse.
    self._add_item(self._pants_arg_long_format_helper, [action])
    super(PantsHelpFormatter, self).add_argument(action)
