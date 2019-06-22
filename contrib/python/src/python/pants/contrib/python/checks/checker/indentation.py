# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import tokenize

from pants.contrib.python.checks.checker.common import CheckstylePlugin


# TODO(wickman) Update this to sanitize line continuation styling as we have
# disabled it from pycodestyle.py due to mismatched indentation styles.
class Indentation(CheckstylePlugin):
  """Enforce proper indentation."""

  @classmethod
  def name(cls):
    return 'indentation'

  INDENT_LEVEL = 2  # the one true way

  def nits(self):
    indents = []

    for token in self.python_file.tokens:
      token_type, token_text, token_start = token[0:3]
      if token_type is tokenize.INDENT:
        last_indent = len(indents[-1]) if indents else 0
        current_indent = len(token_text)
        if current_indent - last_indent != self.INDENT_LEVEL:
          yield self.error('T100',
              'Indentation of {} instead of {}'.format(
                current_indent - last_indent, self.INDENT_LEVEL),
              token_start[0])
        indents.append(token_text)
      elif token_type is tokenize.DEDENT:
        indents.pop()
