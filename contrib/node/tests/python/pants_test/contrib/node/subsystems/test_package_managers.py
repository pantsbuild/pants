# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
import unittest.mock

from pants.contrib.node.subsystems.package_managers import (
    PackageInstallationTypeOption,
    PackageInstallationVersionOption,
    PackageManagerNpm,
    PackageManagerYarnpkg,
)


def fake_install():
    return "fake_install_dir"


@unittest.mock.patch("pants.contrib.node.subsystems.package_managers.command_gen")
class TestYarnpkg(unittest.TestCase):
    def setUp(self):
        self.yarnpkg = PackageManagerYarnpkg([fake_install])

    def test_run_cli(self, mock_command_gen):
        fake_cli = "fake_cli"
        args = ["arg1", "arg2"]

        self.yarnpkg.run_cli(fake_cli, args=args)
        mock_command_gen.assert_called_once_with(
            [fake_install], "yarnpkg", args=([fake_cli, "--"] + args), node_paths=None
        )

    def test_run_script(self, mock_command_gen):
        script_name = "script_name"
        script_args = ["arg1", "arg2"]
        self.yarnpkg.run_script(script_name, script_args=script_args)
        mock_command_gen.assert_called_once_with(
            [fake_install],
            "yarnpkg",
            args=(["run", script_name, "--"] + script_args),
            node_paths=None,
        )

    def test_install_module_options_off(self, mock_command_gen):
        self.yarnpkg.install_module(
            install_optional=False, production_only=False, force=False, frozen_lockfile=True
        )
        mock_command_gen.assert_called_once_with(
            [fake_install],
            "yarnpkg",
            args=["--non-interactive", "--ignore-optional", "--frozen-lockfile"],
            node_paths=None,
        )

    def test_install_module_options_on(self, mock_command_gen):
        self.yarnpkg.install_module(
            install_optional=True, production_only=True, force=True, frozen_lockfile=True
        )
        mock_command_gen.assert_called_once_with(
            [fake_install],
            "yarnpkg",
            args=["--non-interactive", "--production=true", "--force", "--frozen-lockfile"],
            node_paths=None,
        )

    def test_add_package_default(self, mock_command_gen):
        package_name = "package_name"
        self.yarnpkg.add_package(package_name)
        mock_command_gen.assert_called_once_with(
            [fake_install], "yarnpkg", args=["add", package_name], node_paths=None
        )

    def test_add_package_other_options(self, mock_command_gen):
        package_name = "package_name"
        for type_option, expected_args in {
            PackageInstallationTypeOption.DEV: ["--dev"],
            PackageInstallationTypeOption.PEER: ["--peer"],
            PackageInstallationTypeOption.OPTIONAL: ["--optional"],
            PackageInstallationTypeOption.BUNDLE: [],
            PackageInstallationTypeOption.NO_SAVE: [],
        }.items():
            self.yarnpkg.add_package(
                package_name, type_option=type_option,
            )
            mock_command_gen.assert_called_once_with(
                [fake_install],
                "yarnpkg",
                args=["add", package_name] + expected_args,
                node_paths=None,
            )
            mock_command_gen.reset_mock()
        for version_option, expected_args in {
            PackageInstallationVersionOption.EXACT: ["--exact"],
            PackageInstallationVersionOption.TILDE: ["--tilde"],
        }.items():
            self.yarnpkg.add_package(
                package_name, version_option=version_option,
            )
            mock_command_gen.assert_called_once_with(
                [fake_install],
                "yarnpkg",
                args=["add", package_name] + expected_args,
                node_paths=None,
            )
            mock_command_gen.reset_mock()


@unittest.mock.patch("pants.contrib.node.subsystems.package_managers.command_gen")
class TestNpm(unittest.TestCase):
    def setUp(self):
        self.npm = PackageManagerNpm([fake_install])

    def test_run_cli(self, mock_command_gen):
        fake_cli = "fake_cli"
        args = ["arg1", "arg2"]

        self.assertRaises(RuntimeError, self.npm.run_cli, fake_cli, args=args)

    def test_run_script(self, mock_command_gen):
        script_name = "script_name"
        script_args = ["arg1", "arg2"]
        self.npm.run_script(script_name, script_args=script_args)
        mock_command_gen.assert_called_once_with(
            [fake_install],
            "npm",
            args=(["run-script", script_name, "--"] + script_args),
            node_paths=None,
        )

    def test_install_module_options_off(self, mock_command_gen):
        self.npm.install_module(install_optional=False, production_only=False, force=False)
        mock_command_gen.assert_called_once_with(
            [fake_install], "npm", args=["install", "--no-optional"], node_paths=None
        )

    def test_install_module_options_on(self, mock_command_gen):
        self.npm.install_module(install_optional=True, production_only=True, force=True)
        mock_command_gen.assert_called_once_with(
            [fake_install], "npm", args=["install", "--production", "--force"], node_paths=None
        )

    def test_add_package_default(self, mock_command_gen):
        package_name = "package_name"
        self.npm.add_package(package_name)
        mock_command_gen.assert_called_once_with(
            [fake_install], "npm", args=["install", package_name, "--save-prod"], node_paths=None
        )

    def test_add_package_other_options(self, mock_command_gen):
        package_name = "package_name"
        for type_option, expected_args in {
            PackageInstallationTypeOption.DEV: ["--save-dev"],
            PackageInstallationTypeOption.PEER: [],
            PackageInstallationTypeOption.OPTIONAL: ["--save-optional"],
            PackageInstallationTypeOption.BUNDLE: ["--save-bundle"],
            PackageInstallationTypeOption.NO_SAVE: ["--no-save"],
        }.items():
            self.npm.add_package(
                package_name, type_option=type_option,
            )
            mock_command_gen.assert_called_once_with(
                [fake_install],
                "npm",
                args=["install", package_name] + expected_args,
                node_paths=None,
            )
            mock_command_gen.reset_mock()
        for version_option, expected_args in {
            PackageInstallationVersionOption.EXACT: ["--save-exact"],
            PackageInstallationVersionOption.TILDE: [],
        }.items():
            self.npm.add_package(
                package_name, version_option=version_option,
            )
            mock_command_gen.assert_called_once_with(
                [fake_install],
                "npm",
                args=["install", package_name, "--save-prod"] + expected_args,
                node_paths=None,
            )
            mock_command_gen.reset_mock()
