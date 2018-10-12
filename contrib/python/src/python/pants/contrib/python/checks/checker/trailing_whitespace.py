# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import sys
import tokenize
from builtins import range
from collections import defaultdict

from pants.contrib.python.checks.checker.common import CheckstylePlugin


class TrailingWhitespace(CheckstylePlugin):
  """Warn on invalid trailing whitespace."""

  @classmethod
  def name(cls):
    return 'trailing-whitespace'

  @classmethod
  def build_exception_map(cls, tokens):
    """Generates a set of ranges where we accept trailing slashes, specifically within comments
       and strings.
    """
    exception_ranges = defaultdict(list)
    for token in tokens:
      token_type, _, token_start, token_end = token[0:4]
      if token_type in (tokenize.COMMENT, tokenize.STRING):
        if token_start[0] == token_end[0]:
          exception_ranges[token_start[0]].append((token_start[1], token_end[1]))
        else:
          exception_ranges[token_start[0]].append((token_start[1], sys.maxsize))
          for line in range(token_start[0] + 1, token_end[0]):
            exception_ranges[line].append((0, sys.maxsize))
          exception_ranges[token_end[0]].append((0, token_end[1]))
    return exception_ranges

  def __init__(self, *args, **kw):
    super(TrailingWhitespace, self).__init__(*args, **kw)
    self._exception_map = self.build_exception_map(self.python_file.tokens)

  def has_exception(self, line_number, exception_start, exception_end=None):
    exception_end = exception_end or exception_start
    for start, end in self._exception_map.get(line_number, ()):
      if start <= exception_start and exception_end <= end:
        return True
    return False

  def nits(self):
    for line_number, line in self.python_file.enumerate():
      stripped_line = line.rstrip()
      if stripped_line != line and not self.has_exception(line_number,
          len(stripped_line), len(line)):
        yield self.error('T200', 'Line has trailing whitespace.', line_number)
      if line.rstrip().endswith('\\'):
        if not self.has_exception(line_number, len(line.rstrip()) - 1):
          yield self.error('T201', 'Line has trailing slashes.', line_number)
