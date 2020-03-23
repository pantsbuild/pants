# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class MetaRenameIntegrationTest(PantsRunIntegrationTest):
    def test_meta_rename(self):

        pre_dependees_run = self.run_pants(
            ["dependees", "testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:X"]
        )

        self.run_pants(
            [
                "meta-rename",
                "--from=testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:X",
                "--to=testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:Y",
                "testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:X",
            ]
        )

        post_dependees_run = self.run_pants(
            ["dependees", "testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:Y"]
        )

        self.run_pants(
            [
                "meta-rename",
                "--from=testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:Y",
                "--to=testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:X",
                "testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:Y",
            ]
        )

        self.assertEqual(pre_dependees_run.stdout_data, post_dependees_run.stdout_data)
