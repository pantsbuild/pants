# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

import antlr3
import antlr3.tree
from pants_antlr.test.eval.Eval import Eval
from pants_antlr.test.eval.ExprLexer import ExprLexer
from pants_antlr.test.eval.ExprParser import ExprParser


def main(expr):
  """Code that emits the value of a simple arithmetic expression.

  Exercises interaction with ANTLR3-generated Python code.

  This code is modified from the canonical example
  at http://www.antlr.org/wiki/display/ANTLR3/Example.
  """
  char_stream = antlr3.ANTLRStringStream('{}\n'.format(expr))
  lexer = ExprLexer(char_stream)
  tokens = antlr3.CommonTokenStream(lexer)
  parser = ExprParser(tokens)
  r = parser.prog()

  # this is the root of the AST
  root = r.tree

  nodes = antlr3.tree.CommonTreeNodeStream(root)
  nodes.setTokenStream(tokens)
  eval = Eval(nodes)
  eval.prog()


if __name__ == '__main__':
  main(' '.join(sys.argv[1:]))
