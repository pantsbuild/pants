# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast
import re
import token
import tokenize
from io import StringIO

from six import PY3

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

  @classmethod
  def string_node_token_names(cls, str_node_text):
    """Get the individual tokens of the source text of the string ast node.

    In Python 3, strings with this implicit concatenation across multiple lines with inconsistent
    indentation can be tokenized as incorrect, even though Python 3 accepts it, since we don't
    capture the containing pair of parentheses which allows the string to be parsed
    correctly. For example, this source text can be parsed correctly when Python 3 executes it:

        ("$(if [ -e ./{0} -a -e ./{1} ]; then echo 'mark_success'; "
         "elif [ -e ./{1} ]; then echo 'mark_failed'; "
        "else echo 'no_op'; fi)")

    but since the text of the string node that we get from asttokens always begins with zero
    indentation, this lint would raise:

          File "<tokenize>", line 3
          "else echo 'no_op'; fi)"
          ^
        IndentationError: unindent does not match any outer indentation level

    Stripping leading whitespace from each line of the string node avoids this error when it occurs,
    and doesn't change the resulting tokenization. We can rely on the Python 3 interpreter to raise
    an error beforehand if the syntax is truly incorrect.
    """
    try:
      tokens = list(tokenize.generate_tokens(StringIO(str_node_text).readline))
    except IndentationError:
      unindented_string = re.sub(r'^\s+', '', str_node_text, flags=re.MULTILINE)
      tokens = list(tokenize.generate_tokens(StringIO(unindented_string).readline))
    for tok in tokens:
      token_type = tok.type if PY3 else tok[0]
      yield token.tok_name[token_type]

  @classmethod
  def has_multiple_strings(cls, token_names):
    return sum(1 if name == 'STRING' else 0 for name in token_names) > 1

  def uses_implicit_concatenation(self, str_node_text):
    str_node_token_names = list(self.string_node_token_names(str_node_text))
    return self.has_multiple_strings(str_node_token_names)

  def nits(self):
    for str_node in self.iter_strings(self.python_file.tree):
      str_node_text = self.python_file.tokenized_file_body.get_text(str_node)
      if self.uses_implicit_concatenation(str_node_text):
        yield self.warning(
          'T806',
          """\
Implicit string concatenation by separating string literals with a space was detected. Using an
explicit `+` operator can lead to less error-prone code.""",
          str_node)
      # TODO: also consider checking when triple-quoted strings are used -- e.g. '''a''''' becomes
      # just "a" (from implicit concatenation, which we catch here), but '''''a''' turns into "''a",
      # without any implicit concatenation.
