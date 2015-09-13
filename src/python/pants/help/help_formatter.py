# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import wrap

from colors import blue, cyan, green, red

from pants.help.help_info_extracter import HelpInfoExtracter


class HelpFormatter(object):
  def __init__(self, scope, show_recursive, show_advanced, color):
    self._scope = scope
    self._show_recursive = show_recursive
    self._show_advanced = show_advanced
    self._color = color

  def _maybe_blue(self, s):
    return self._maybe_color(blue, s)

  def _maybe_cyan(self, s):
    return self._maybe_color(cyan, s)

  def _maybe_green(self, s):
    return self._maybe_color(green, s)

  def _maybe_red(self, s):
    return self._maybe_color(red, s)

  def _maybe_color(self, color, s):
    return color(s) if self._color else s

  def format_options(self, scope, description, registration_args):
    """Return a help message for the specified options.

    :param registration_args: A list of (args, kwargs) pairs, as passed in to options registration.
    """
    oshi = HelpInfoExtracter(self._scope).get_option_scope_help_info(registration_args)
    lines = []
    def add_option(category, ohis):
      if ohis:
        lines.append('')
        display_scope = scope or 'Global'
        if category:
          lines.append(self._maybe_blue('{} {} options:'.format(display_scope, category)))
        else:
          lines.append(self._maybe_blue('{} options:'.format(display_scope)))
          if description:
            lines.append(description)
        lines.append(' ')
        for ohi in ohis:
          lines.extend(self.format_option(ohi))
    add_option('', oshi.basic)
    if self._show_recursive:
      add_option('recursive', oshi.recursive)
    if self._show_advanced:
      add_option('advanced', oshi.advanced)
    return lines

  def format_option(self, ohi):
    lines = []
    arg_line = ('{args} {fromfile}{dflt}'
                .format(args=self._maybe_cyan(', '.join(ohi.display_args)),
                        dflt=self._maybe_green('(default: {})'.format(ohi.default)),
                        fromfile=self._maybe_green('(@fromfile value supported) ' if ohi.fromfile
                                                   else '')))
    lines.append(arg_line)

    indent = '    '
    lines.extend(['{}{}'.format(indent, s) for s in wrap(ohi.help, 76)])
    if ohi.deprecated_message:
      lines.append(self._maybe_red('{}{}.'.format(indent, ohi.deprecated_message)))
      if ohi.deprecated_hint:
        lines.append(self._maybe_red('{}{}'.format(indent, ohi.deprecated_hint)))
    return lines
