# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import unittest

import antlr3
import antlr3.tree

from twitter.pants.python.test.ExprLexer import ExprLexer
from twitter.pants.python.test.ExprParser import ExprParser
from twitter.pants.python.test.Eval import Eval

# We import this gratuitously, just to test that namespace packages work correctly in the
# generated ANTLR code. This module shares a namespace prefix with the generated
# ANTLR code, and so will be masked by it if namespace packages are broken.
from twitter.pants.python.test2.csvLexer import csvLexer



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
