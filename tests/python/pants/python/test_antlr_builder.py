# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

import antlr3
import antlr3.tree
from twitter.common.python.test.Eval import Eval
from twitter.common.python.test.ExprLexer import ExprLexer
from twitter.common.python.test.ExprParser import ExprParser


# We import this gratuitously, just to test that namespace packages work correctly in the
# generated ANTLR code. This module shares a namespace prefix with the generated
# ANTLR code, and so will be masked by it if namespace packages are broken.
from twitter.common.python.test2.csvLexer import csvLexer

class AntlrBuilderTest(unittest.TestCase):
  def test_generated_parser(self):
    """The 'test' here is the very fact that we can successfully import the generated antlr code.
    However there's no harm in also exercising it. This code is modified from the canonical example
    at http://www.antlr.org/wiki/display/ANTLR3/Example ."""
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
