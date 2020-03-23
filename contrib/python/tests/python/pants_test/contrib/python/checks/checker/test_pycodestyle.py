# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.contrib.python.checks.checker.plugin_test_base import CheckstylePluginTestBase

from pants.contrib.python.checks.checker.pycodestyle import PyCodeStyleChecker


class PyCodeStyleCheckerTest(CheckstylePluginTestBase):
    plugin_type = PyCodeStyleChecker

    @property
    def file_required(self):
        return True

    def get_plugin(self, file_content, **options):
        return super().get_plugin(
            file_content,
            max_length=options.get("max_length", 10),
            ignore=options.get("ignore", False),
        )

    def test_pycodestyle(self):
        self.assertNoNits("")

    def test_pycodestyle_line_length(self):
        self.assertNit("# Longer than 10.\n", "E501", expected_line_number="001")

    def test_pycodestyle_nit_lines(self):
        # Pycodestyle supports `# noqa` for certain checks, but not all, whereas the higher level pants
        # checker always supports `# noqa` no matter the provenance of the check, iff the check has a
        # relevant line marked `# noqa`.
        #
        # This test verifies that E221 does not respect `# noqa` at the pycodestyle check level, but
        # that the resulting nit does have an appropriate set of lines for the higher-level pants
        # checker `# noqa` support.
        nit = self.assertNit('A  = "Longer than 10."  # noqa\n', "E221", expected_line_number="001")
        self.assertEqual(['A  = "Longer than 10."  # noqa'], nit.lines)
