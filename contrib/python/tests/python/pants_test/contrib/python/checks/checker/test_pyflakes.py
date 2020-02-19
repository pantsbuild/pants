# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.contrib.python.checks.checker.plugin_test_base import CheckstylePluginTestBase

from pants.contrib.python.checks.checker.pyflakes import PyflakesChecker


class PyflakesCheckerTest(CheckstylePluginTestBase):
    plugin_type = PyflakesChecker

    def get_plugin(self, file_content, **options):
        return super().get_plugin(file_content, ignore=options.get("ignore") or [])

    def test_pyflakes(self):
        self.assertNoNits("")

    def test_pyflakes_unused_import(self):
        try:
            self.assertNit("import os", "F401", expected_line_number="001")
        except AssertionError:
            # N.B. For some reason, on Python 3.6 Pyflakes marks the nit as taking two lines.
            # This cannot be reproduced with Python 2.7, 3.4, 3.5, or 3.7. I cannot find on Pyflakes
            # any documentation for why this is happening, but it appears to be an issue with Pyflakes
            # rather than with Pants.
            self.assertNit("import os", "F401", expected_line_number="001-002")

    def test_pyflakes_ignore(self):
        plugin = self.get_plugin("import os", ignore=["UnusedImport"])
        self.assertEqual([], list(plugin.nits()))
