# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import sys

import antlr4
import antlr4.tree
from pants_antlr.test.eval.testprojects.src.antlr.python.test.EvalListener import (
    EvalListener,
    ExprLexer,
    ExprParser,
)


def main(expr):
    """Code that emits the value of a simple arithmetic expression.

    Exercises interaction with ANTLR3-generated Python code.

    This code is modified from the canonical example
    at http://www.antlr.org/wiki/display/ANTLR3/Example.
    """
    char_stream = antlr4.InputStream("{}\n".format(expr))
    lexer = ExprLexer(char_stream)
    tokens = antlr4.CommonTokenStream(lexer)
    parser = ExprParser(tokens)
    r = parser.prog()

    # this is the root of the AST
    root = r.tree

    nodes = antlr4.tree.CommonTreeNodeStream(root)
    nodes.setTokenStream(tokens)
    eval = EvalListener(nodes)
    eval.prog()


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]))
