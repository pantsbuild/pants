# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os

from pants.base.exceptions import TaskError
from pants.binaries.binary_tool import NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.util.dirutil import is_readable_dir
from pants.util.memo import memoized_method, memoized_property

from pants.contrib.node.subsystems.command import command_gen
from pants.contrib.node.subsystems.package_managers import (
    PACKAGE_MANAGER_NPM,
    PACKAGE_MANAGER_YARNPKG,
    PACKAGE_MANAGER_YARNPKG_ALIAS,
    VALID_PACKAGE_MANAGERS,
    PackageManagerNpm,
    PackageManagerYarnpkg,
)
from pants.contrib.node.subsystems.yarnpkg_distribution import YarnpkgDistribution

logger = logging.getLogger(__name__)


class NodeReleaseUrlGenerator(BinaryToolUrlGenerator):

    _DIST_URL_FMT = "https://nodejs.org/dist/{version}/node-{version}-{system_id}.tar.gz"

    _SYSTEM_ID = {
        "mac": "darwin-x64",
        "linux": "linux-x64",
    }

    def generate_urls(self, version, host_platform):
        system_id = self._SYSTEM_ID[host_platform.os_name]
        return [self._DIST_URL_FMT.format(version=version, system_id=system_id)]


class NodeDistribution(NativeTool):
    """Represents a self-bootstrapping Node distribution."""

    options_scope = "node-distribution"
    name = "node"
    default_version = "v8.11.3"
    archive_type = "tgz"

    def get_external_url_generator(self):
        return NodeReleaseUrlGenerator()

    @classmethod
    def subsystem_dependencies(cls):
        # Note that we use a YarnpkgDistribution scoped to the NodeDistribution, which may itself
        # be scoped to a task.
        return super().subsystem_dependencies() + (YarnpkgDistribution.scoped(cls),)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--package-manager",
            advanced=True,
            default="npm",
            fingerprint=True,
            choices=VALID_PACKAGE_MANAGERS,
            help="Default package manager config for repo. Should be one of {}".format(
                VALID_PACKAGE_MANAGERS
            ),
        )
        register(
            "--node-scope",
            advanced=True,
            fingerprint=True,
            help="Default node scope for repo. Scope groups related packages together.",
        )

    @memoized_method
    def _get_package_managers(self):
        npm = PackageManagerNpm([self._install_node])
        yarnpkg = PackageManagerYarnpkg([self._install_node, self._install_yarnpkg])
        return {
            PACKAGE_MANAGER_NPM: npm,
            PACKAGE_MANAGER_YARNPKG: yarnpkg,
            PACKAGE_MANAGER_YARNPKG_ALIAS: yarnpkg,  # Allow yarn to be used as an alias for yarnpkg
        }

    def get_package_manager(self, package_manager=None):
        package_manager = package_manager or self.get_options().package_manager
        package_manager_obj = self._get_package_managers().get(package_manager)
        if not package_manager_obj:
            raise TaskError(
                "Unknown package manager: {}.\nValid values are {}.".format(
                    package_manager, list(NodeDistribution.VALID_PACKAGE_MANAGER_LIST.keys())
                )
            )
        return package_manager_obj

    @memoized_property
    def node_scope(self):
        return self.get_options().node_scope

    @memoized_method
    def _install_node(self):
        """Install the Node distribution from pants support binaries.

        :returns: The Node distribution bin path.
        :rtype: string
        """
        node_package_path = self.select()
        # Todo: https://github.com/pantsbuild/pants/issues/4431
        # This line depends on repacked node distribution.
        # Should change it from 'node/bin' to 'dist/bin'
        node_bin_path = os.path.join(node_package_path, "node", "bin")
        if not is_readable_dir(node_bin_path):
            # The binary was pulled from nodejs and not our S3, in which
            # case it's installed under a different directory.
            return os.path.join(node_package_path, os.listdir(node_package_path)[0], "bin")
        return node_bin_path

    @memoized_method
    def _install_yarnpkg(self):
        """Install the Yarnpkg distribution from pants support binaries.

        :returns: The Yarnpkg distribution bin path.
        :rtype: string
        """
        yarnpkg_package_path = YarnpkgDistribution.scoped_instance(self).select()
        yarnpkg_bin_path = os.path.join(yarnpkg_package_path, "dist", "bin")
        if not is_readable_dir(yarnpkg_bin_path):
            # The binary was pulled from yarn's Github release page and not our S3,
            # in which case it's installed under a different directory.
            return os.path.join(yarnpkg_package_path, os.listdir(yarnpkg_package_path)[0], "bin")
        return yarnpkg_bin_path

    def node_command(self, args=None, node_paths=None):
        """Creates a command that can run `node`, passing the given args to it.

        :param list args: An optional list of arguments to pass to `node`.
        :param list node_paths: An optional list of paths to node_modules.
        :returns: A `node` command that can be run later.
        :rtype: :class:`NodeDistribution.Command`
        """
        # NB: We explicitly allow no args for the `node` command unlike the `npm` command since running
        # `node` with no arguments is useful, it launches a REPL.
        return command_gen([self._install_node], "node", args=args, node_paths=node_paths)
