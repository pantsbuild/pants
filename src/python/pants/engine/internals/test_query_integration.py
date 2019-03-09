# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon


class ListQueryIntegrationTest(PantsRunIntegrationTest):
    """Test the --query option, which is intended to subsume multiple other options and goals.

    If v2 rules are made to satisfy both existing options such as --owner-of and their equivalent in
    the --query option, the testing for that functionality should be moved into this file (or into
    unit testing), and the separate option or goal should eventually be deprecated.
    """

    # TODO(#7346): test changes-since or changes-for-diffspec queries! It's currently difficult to set
    # up an integration test for changing files.

    @ensure_daemon
    def test_query_success(self):
        pants_run = self.do_command(
            "--query=owner-of testprojects/tests/python/pants/dummies/test_pass.py",
            "list",
            success=True,
        )
        self.assertEqual(
            # TODO: the ordering of v2 list output doesn't appear to be deterministic, so we have to
            # "parse" the output and reconstruct it to reliably match against it.
            "{}\n".format("\n".join(sorted(pants_run.stdout_data.splitlines()))),
            dedent(
                """\
        testprojects/tests/python/pants/dummies:passing_target
        testprojects/tests/python/pants:secondary_source_file_owner
        """
            ),
        )
