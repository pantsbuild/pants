# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast
import re

from pants.contrib.python.checks.checker.common import CheckstylePlugin


class ImplicitStringConcatenation(CheckstylePlugin):
  """Detect instances of implicit string concatenation without a plus sign."""

  @classmethod
  def name(cls):
    return 'implicit-string-concatenation'

  @classmethod
  def iter_strings(cls, tree):
    for ast_node in ast.walk(tree):
      if isinstance(ast_node, ast.Str):
        yield ast_node

  def maybe_uses_implicit_concatenation(self, expr):
    str_node_text = self.python_file.tokenized_file_body.get_text(expr)
    # Search for string nodes of the form 'a' 'b', using any combination of single or double quotes,
    # with any spacing in between them, but don't flag instances of """ or '''. This searches from
    # the start of the string node and parses backslashes.
    # TODO: consider just parsing the string for string components and then raising if there is more
    # than one. This would also allow for more complex logic like reaching into triple-quoted
    # strings.
    if re.match(r"^\s*(('([^']|(\\)*')*'|\"([^\"]|(\\)*\")*\")\s+('([^']|(\\)*')*'|\"([^\"]|(\\)*\")*\")|('([^']|(\\)*')+'|\"([^\"]|(\\)*\")+\")\s*('([^']|(\\)*')+'|\"([^\"]|(\\)*\")+\"))",
                str_node_text):
      return True
    # TODO: also consider checking when triple-quoted strings are used -- e.g. '''''a''' becomes
    # "''a", but '''a''''' is just "a", which is confusing.

  def nits(self):
    for str_node in self.iter_strings(self.python_file.tree):
      if self.maybe_uses_implicit_concatenation(str_node):
        yield self.warning(
          'T806',
          """\
Implicit string concatenation by separating string literals with a space was detected. Using an
explicit `+` operator can lead to less error-prone code.""",
          str_node)
