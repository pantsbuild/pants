# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.parser import BuildFilePreludeSymbols, SymbolTable
from pants.engine.legacy.parser import LegacyPythonCallbacksParser
from pants.option.global_options import BuildFileImportsBehavior
from pants.util.frozendict import FrozenDict


class LegacyPythonCallbacksParserTest(unittest.TestCase):
    def test_no_import_sideeffects(self) -> None:
        # A parser with no symbols registered.
        parser = LegacyPythonCallbacksParser(
            SymbolTable({}),
            BuildFileAliases(),
            build_file_imports_behavior=BuildFileImportsBehavior.warn,
        )
        # Call to import a module should succeed.
        parser.parse(
            "/dev/null",
            b"""import os; os.path.join('x', 'y')""",
            BuildFilePreludeSymbols(FrozenDict()),
        )
        # But the imported module should not be visible as a symbol in further parses.
        with self.assertRaises(NameError):
            parser.parse(
                "/dev/null", b"""os.path.join('x', 'y')""", BuildFilePreludeSymbols(FrozenDict())
            )
