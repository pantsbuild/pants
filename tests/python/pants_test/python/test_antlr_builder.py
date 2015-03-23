# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import antlr3
import antlr3.tree

from pants.backend.python.test.Eval import Eval
from pants.backend.python.test.ExprLexer import ExprLexer
from pants.backend.python.test.ExprParser import ExprParser


class AntlrBuilderTest(unittest.TestCase):
  def test_generated_parser(self):
    """The 'test' here is the very fact that we can successfully import the generated antlr code.
    However there's no harm in also exercising it. This code is modified from the canonical example
    at http://www.antlr.org/wiki/display/ANTLR3/Example.
    """
    char_stream = antlr3.ANTLRStringStream('4 + 5\n')
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
  unittest.main()
