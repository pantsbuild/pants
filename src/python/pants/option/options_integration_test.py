# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from textwrap import dedent

import pytest

from pants.fs.fs import safe_filename_from_path
from pants.testutil.pants_integration_test import PantsIntegrationTest
from pants.util.contextutil import temporary_dir


@pytest.mark.skip("Skip until https://github.com/pantsbuild/pants/issues/10206")
class TestOptionsIntegration(PantsIntegrationTest):
    def test_options_works_at_all(self) -> None:
        self.run_pants(["options"]).assert_success()

    def test_options_scope(self) -> None:
        pants_run = self.run_pants(["options", "--no-colors", "--scope=options"])
        pants_run.assert_success()
        self.assertIn("options.scope = options", pants_run.stdout)
        self.assertIn("options.name = None", pants_run.stdout)
        self.assertNotIn("pytest.timeouts = ", pants_run.stdout)

        pants_run = self.run_pants(["options", "--no-colors", "--scope=pytest"])
        pants_run.assert_success()
        self.assertNotIn("options.colors = False", pants_run.stdout)
        self.assertNotIn("options.scope = options", pants_run.stdout)
        self.assertNotIn("options.name = None", pants_run.stdout)
        self.assertIn("pytest.timeouts = ", pants_run.stdout)

    def test_valid_json(self) -> None:
        pants_run = self.run_pants(["options", "--output-format=json"])
        pants_run.assert_success()
        try:
            output_map = json.loads(pants_run.stdout)
            self.assertIn("time", output_map)
            self.assertEqual(output_map["time"]["source"], "HARDCODED")
            self.assertEqual(output_map["time"]["value"], False)
        except ValueError:
            self.fail("Invalid JSON output")

    def test_valid_json_with_history(self) -> None:
        pants_run = self.run_pants(["options", "--output-format=json", "--show-history"])
        pants_run.assert_success()
        try:
            output_map = json.loads(pants_run.stdout)
            self.assertIn("time", output_map)
            self.assertEqual(output_map["time"]["source"], "HARDCODED")
            self.assertEqual(output_map["time"]["value"], False)
            self.assertEqual(output_map["time"]["history"], [])
            for _, val in output_map.items():
                self.assertIn("history", val)
        except ValueError:
            self.fail("Invalid JSON output")

    def test_options_option(self) -> None:
        pants_run = self.run_pants(
            ["options", "--no-colors", "--name=colors", "--no-skip-inherited"]
        )
        pants_run.assert_success()
        self.assertIn("options.colors = ", pants_run.stdout)
        self.assertIn("pytest.colors = ", pants_run.stdout)
        self.assertNotIn("options.scope = ", pants_run.stdout)

    def test_options_only_overridden(self) -> None:
        pants_run = self.run_pants(["options", "--no-colors", "--only-overridden"])
        pants_run.assert_success()
        self.assertIn("options.only_overridden = True", pants_run.stdout)
        self.assertNotIn("options.scope =", pants_run.stdout)
        self.assertNotIn("from HARDCODED", pants_run.stdout)
        self.assertNotIn("from NONE", pants_run.stdout)

    def test_options_rank(self) -> None:
        pants_run = self.run_pants(["options", "--no-colors", "--rank=FLAG"])
        pants_run.assert_success()
        self.assertIn("options.rank = ", pants_run.stdout)
        self.assertIn("(from FLAG)", pants_run.stdout)
        self.assertNotIn("(from CONFIG", pants_run.stdout)
        self.assertNotIn("(from HARDCODED", pants_run.stdout)
        self.assertNotIn("(from NONE", pants_run.stdout)

    def test_options_show_history(self) -> None:
        pants_run = self.run_pants(
            ["options", "--no-colors", "--only-overridden", "--show-history"]
        )
        pants_run.assert_success()
        self.assertIn("options.only_overridden = True", pants_run.stdout)
        self.assertIn("overrode False (from HARDCODED", pants_run.stdout)

    def test_from_config(self) -> None:
        with temporary_dir(root_dir=os.path.abspath(".")) as tempdir:
            config_path = os.path.relpath(os.path.join(tempdir, "config.toml"))
            with open(config_path, "w+") as f:
                f.write(
                    dedent(
                        """
                        [options]
                        colors = false
                        scope = "options"
                        only_overridden = true
                        show_history = true
                        """
                    )
                )
            pants_run = self.run_pants([f"--pants-config-files={config_path}", "options"])
            pants_run.assert_success()
            self.assertIn("options.only_overridden = True", pants_run.stdout)
            self.assertIn(f"(from CONFIG in {config_path})", pants_run.stdout)

    def test_options_deprecation_from_config(self) -> None:
        with temporary_dir(root_dir=os.path.abspath(".")) as tempdir:
            config_path = os.path.relpath(os.path.join(tempdir, "config.toml"))
            with open(config_path, "w+") as f:
                f.write(
                    dedent(
                        """
                        [GLOBAL]
                        verify_config = false
                        pythonpath = [
                            "%(buildroot)s/testprojects/src/python",
                          ]

                        backend_packages = [
                            "plugins.dummy_options",
                          ]

                        [options]
                        colors = false
                        """
                    )
                )
            pants_run = self.run_pants([f"--pants-config-files={config_path}", "options"])
        pants_run.assert_success()
        self.assertIn("mock-options.normal_option", pants_run.stdout)
        self.assertIn("mock-options.crufty_deprecated_but_still_functioning", pants_run.stdout)

    def test_from_config_invalid_section(self) -> None:
        with temporary_dir(root_dir=os.path.abspath(".")) as tempdir:
            config_path = os.path.relpath(os.path.join(tempdir, "config.toml"))
            with open(config_path, "w+") as f:
                f.write(
                    dedent(
                        """
                        [DEFAULT]
                        some_crazy_thing = 123

                        [invalid_scope]
                        colors = false
                        scope = "options"

                        [another_invalid_scope]
                        colors = false
                        scope = "options"
                        """
                    )
                )
            pants_run = self.run_pants([f"--pants-config-files={config_path}", "roots"])
            pants_run.assert_failure()
            self.assertIn("ERROR] Invalid scope [invalid_scope]", pants_run.stderr)
            self.assertIn("ERROR] Invalid scope [another_invalid_scope]", pants_run.stderr)

    def test_from_config_invalid_option(self) -> None:
        with temporary_dir(root_dir=os.path.abspath(".")) as tempdir:
            config_path = os.path.relpath(os.path.join(tempdir, "config.toml"))
            with open(config_path, "w+") as f:
                f.write(
                    dedent(
                        """
                        [DEFAULT]
                        some_crazy_thing = 123

                        [pytest]
                        timeouts = true
                        invalid_option = true
                        """
                    )
                )
            pants_run = self.run_pants([f"--pants-config-files={config_path}", "goals"])
            pants_run.assert_failure()
            self.assertIn("ERROR] Invalid option 'invalid_option' under [pytest]", pants_run.stderr)

    def test_from_config_invalid_global_option(self) -> None:
        """This test can be interpreted in two ways:

        1. An invalid global option `invalid_global` will be caught.
        2. Variable `invalid_global` is not allowed in [GLOBAL].
        """
        with temporary_dir(root_dir=os.path.abspath(".")) as tempdir:
            config_path = os.path.relpath(os.path.join(tempdir, "config.toml"))
            with open(config_path, "w+") as f:
                f.write(
                    dedent(
                        """
                        [DEFAULT]
                        some_crazy_thing = 123

                        [GLOBAL]
                        invalid_global = true
                        another_invalid_global = false
                        """
                    )
                )
            pants_run = self.run_pants([f"--pants-config-files={config_path}", "goals"])
            pants_run.assert_failure()
            self.assertIn("ERROR] Invalid option 'invalid_global' under [GLOBAL]", pants_run.stderr)
            self.assertIn(
                "ERROR] Invalid option 'another_invalid_global' under [GLOBAL]",
                pants_run.stderr,
            )

    def test_invalid_command_line_option_and_invalid_config(self) -> None:
        """Make sure invalid command line error will be thrown and exits."""
        with temporary_dir(root_dir=os.path.abspath(".")) as tempdir:
            config_path = os.path.relpath(os.path.join(tempdir, "config.toml"))
            with open(config_path, "w+") as f:
                f.write(
                    dedent(
                        """
                        [pytest]
                        bad_option = true

                        [invalid_scope]
                        abc = 123
                        """
                    )
                )

            # Run with invalid config and invalid command line option.
            # Should error out with invalid command line option only.
            pants_run = self.run_pants(
                [f"--pants-config-files={config_path}", "--pytest-invalid=ALL", "goals"]
            )
            pants_run.assert_failure()
            self.assertIn(
                "Unrecognized command line flag '--invalid' on scope 'pytest'",
                pants_run.stderr,
            )

            # Run with invalid config only.
            # Should error out with `bad_option` and `invalid_scope` in config.
            pants_run = self.run_pants([f"--pants-config-files={config_path}", "goals"])
            pants_run.assert_failure()
            self.assertIn("ERROR] Invalid option 'bad_option' under [pytest]", pants_run.stderr)
            self.assertIn("ERROR] Invalid scope [invalid_scope]", pants_run.stderr)

    def test_command_line_option_unused_by_goals(self) -> None:
        self.run_pants(["filter", "--test-debug"]).assert_success()
        self.run_pants(["filter", "--debug"]).assert_failure()

    def test_skip_inherited(self) -> None:
        pants_run = self.run_pants(
            [
                "--backend-packages=pants.backend.python",
                "--no-colors",
                "--no-pytest-colors",
                "--setup-py-colors",
                "options",
                "--skip-inherited",
                "--name=colors",
            ]
        )
        pants_run.assert_success()
        unstripped_lines = (s.split("(", 1)[0] for s in pants_run.stdout.split("\n") if "(" in s)
        lines = [s.strip() for s in unstripped_lines]
        # This should be included because it has no super-scopes.
        self.assertIn("colors = False", lines)
        # These should be included because they differ from the super-scope value.
        self.assertIn("setup-py.colors = True", lines)
        # These should be omitted because they have the same value as their super-scope.
        self.assertNotIn("pytest.colors = False", lines)

    def test_pants_ignore_option(self) -> None:
        with temporary_dir(root_dir=os.path.abspath(".")) as tempdir:
            config_path = os.path.relpath(os.path.join(tempdir, "config.toml"))
            with open(config_path, "w+") as f:
                f.write(
                    dedent(
                        """
                        [GLOBAL]
                        pants_ignore.add = ['some/random/dir']
                        """
                    )
                )
            pants_run = self.run_pants(
                [f"--pants-config-files={config_path}", "--no-colors", "options"]
            )
            pants_run.assert_success()
            self.assertIn(
                f"pants_ignore = ['.*/', '/dist/', 'some/random/dir'] (from CONFIG in {config_path})",
                pants_run.stdout,
            )

    def test_pants_symlink_workdirs(self) -> None:
        with temporary_dir() as tmp_dir:
            symlink_workdir = f"{tmp_dir}/.pants.d"
            physical_workdir_base = f"{tmp_dir}/workdirs"
            physical_workdir = f"{physical_workdir_base}/{safe_filename_from_path(symlink_workdir)}"

            pants_run = self.run_pants_with_workdir(
                [f"--pants-physical-workdir-base={physical_workdir_base}", "help"],
                workdir=symlink_workdir,
            )
            pants_run.assert_success()
            # Make sure symlink workdir is pointing to physical workdir
            self.assertTrue(os.readlink(symlink_workdir) == physical_workdir)

            self.run_pants_with_workdir(
                [f"--pants-physical-workdir-base={physical_workdir_base}", "clean-all"],
                workdir=symlink_workdir,
            )
            # Make sure both physical_workdir and symlink_workdir are empty after running clean-all
            self.assertTrue(not os.listdir(symlink_workdir) and not os.listdir(physical_workdir))
