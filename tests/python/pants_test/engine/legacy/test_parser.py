# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.legacy.parser import LegacyPythonCallbacksParser
from pants.engine.parser import EmptyTable


class LegacyPythonCallbacksParserTest(unittest.TestCase):

  def test_no_import_sideeffects(self):
    # A parser with no symbols registered.
    parser = LegacyPythonCallbacksParser(EmptyTable(), BuildFileAliases(), build_file_imports_behavior='allow')
    # Call to import a module should succeed.
    parser.parse('/dev/null', '''import os; os.path.join('x', 'y')''')
    # But the imported module should not be visible as a symbol in further parses.
    with self.assertRaises(NameError):
      parser.parse('/dev/null', '''os.path.join('x', 'y')''')
