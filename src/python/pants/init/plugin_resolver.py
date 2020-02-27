# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import logging
import os
import shutil
import site
import uuid

from pex import resolver
from pex.interpreter import PythonInterpreter
from pkg_resources import Distribution
from pkg_resources import working_set as global_working_set

from pants.option.global_options import GlobalOptionsRegistrar
from pants.python.python_repos import PythonRepos
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_concurrent_rename, safe_delete, safe_open
from pants.util.memo import memoized_property
from pants.util.strutil import ensure_text
from pants.version import PANTS_SEMVER

logger = logging.getLogger(__name__)


class PluginResolver:
    @staticmethod
    def _is_wheel(path):
        return os.path.isfile(path) and path.endswith(".whl")

    def __init__(self, options_bootstrapper, *, interpreter=None):
        self._options_bootstrapper = options_bootstrapper
        self._interpreter = interpreter or PythonInterpreter.get()

        bootstrap_options = self._options_bootstrapper.get_bootstrap_options().for_global_scope()
        self._plugin_requirements = sorted(
            set(bootstrap_options.plugins) | set(bootstrap_options.plugins2)
        )
        self._plugin_cache_dir = bootstrap_options.plugin_cache_dir
        self._plugins_force_resolve = bootstrap_options.plugins_force_resolve

    def resolve(self, working_set=None):
        """Resolves any configured plugins and adds them to the global working set.

        :param working_set: The working set to add the resolved plugins to instead of the global
                            working set (for testing).
        :type: :class:`pkg_resources.WorkingSet`
        """
        working_set = working_set or global_working_set
        if self._plugin_requirements:
            for resolved_plugin_location in self._resolve_plugin_locations():
                site.addsitedir(
                    resolved_plugin_location
                )  # Activate any .pth files plugin wheels may have.
                working_set.add_entry(resolved_plugin_location)
        return working_set

    def _resolve_plugin_locations(self):
        hasher = hashlib.sha1()

        # Assume we have platform-specific plugin requirements and pessimistically mix the ABI
        # identifier into the hash to ensure re-resolution of plugins for different interpreter ABIs.
        hasher.update(self._interpreter.identity.abi_tag.encode())  # EG: cp36m

        for req in sorted(self._plugin_requirements):
            hasher.update(req.encode())
        resolve_hash = hasher.hexdigest()
        resolved_plugins_list = os.path.join(self.plugin_cache_dir, f"plugins-{resolve_hash}.txt")

        if self._plugins_force_resolve:
            safe_delete(resolved_plugins_list)

        if not os.path.exists(resolved_plugins_list):
            tmp_plugins_list = f"{resolved_plugins_list}.{uuid.uuid4().hex}"
            with safe_open(tmp_plugins_list, "w") as fp:
                for plugin in self._resolve_plugins():
                    fp.write(ensure_text(plugin))
                    fp.write("\n")
            os.rename(tmp_plugins_list, resolved_plugins_list)
        with open(resolved_plugins_list, "r") as fp:
            for plugin in fp:
                plugin_path = plugin.strip()
                plugin_location = f"{self._plugin_location(plugin_path)}"
                yield plugin_location

    def _resolve_plugins(self):
        logger.info(
            "Resolving new plugins...:\n  {}".format("\n  ".join(self._plugin_requirements))
        )
        resolved_dists = resolver.resolve(
            self._plugin_requirements,
            indexes=self._python_repos.indexes,
            find_links=self._python_repos.repos,
            interpreter=self._interpreter,
            cache=self.plugin_cache_dir,
            allow_prereleases=PANTS_SEMVER.is_prerelease,
        )
        return [
            self._install_plugin(resolved_dist.distribution) for resolved_dist in resolved_dists
        ]

    @classmethod
    def _plugin_location(cls, plugin_path):
        return f"{plugin_path}-install"

    def _install_plugin(self, distribution: Distribution):
        # We don't actually install the distribution. It's installed for us by the Pex resolver in
        # a chroot. We just copy that chroot out of the Pex cache to a location we control.
        # Historically though, Pex did not install wheels it resolved and we did this here by hand.
        # We retain the terminology and, more importantly, the final resting "install" path and the
        # contents of plugin-<hash>.txt files to keep the plugin cache forwards and backwards
        # compatible between Pants releases.
        #
        # Concretely:
        #
        # 1. In the past Pex resolved the wheel file below and we installed it to the "-install"
        #    directory:
        #
        #    ~/.cache/pants/plugins/
        #       requests-2.23.0-py2.py3-none-any.whl
        #       requests-2.23.0-py2.py3-none-any.whl-install/
        #
        #    The plugins-<hash>.txt file that records plugin locations contained the un-installed
        #    wheel file path:
        #
        #    $ cat ~/.cache/pants/plugins/plugins-418c36b574edbcf4720b266b0709750ad588c281.txt
        #    /home/jsirois/.cache/pants/plugins/requests-2.23.0-py2.py3-none-any.whl
        #
        # 2. Now Pex resolves an installed wheel chroot directory and we copy that directory to the
        #    "-install" directory:
        #
        #    ~/.cache/pants/plugins/
        #      installed_wheels/6ce6cd759a2d13badb1f6b9e665e2aded7a012dd/requests-2.23.0-py2.py3-none-any.whl/
        #      requests-2.23.0-py2.py3-none-any.whl-install/
        #
        #    The plugins-<hash>.txt file that records plugin locations now contains the final
        #    installed wheel path with the "-install" suffix omitted which leads to the same file
        #    contents as past Pants versions:
        #
        #    $ cat ~/.cache/pants/plugins/plugins-418c36b574edbcf4720b266b0709750ad588c281.txt
        #        /home/jsirois/.cache/pants/plugins/requests-2.23.0-py2.py3-none-any.whl
        #
        #    We add the suffix on after reading the file to find the actual installed wheel path.

        wheel_basename = os.path.basename(distribution.location)
        plugin_path = os.path.join(self.plugin_cache_dir, wheel_basename)

        with temporary_dir() as td:
            temp_install_dir = os.path.join(td, wheel_basename)
            shutil.copytree(distribution.location, temp_install_dir)
            safe_concurrent_rename(temp_install_dir, self._plugin_location(plugin_path))
            return plugin_path

    @property
    def plugin_cache_dir(self):
        """The path of the directory pants plugins bdists are cached in."""
        return self._plugin_cache_dir

    @memoized_property
    def _python_repos(self):
        return self._create_global_subsystem(PythonRepos)

    def _create_global_subsystem(self, subsystem_type):
        options_scope = subsystem_type.options_scope

        # NB: The PluginResolver runs very early in the pants startup sequence before the standard
        # Subsystem facility is wired up.  As a result PluginResolver is not itself a Subsystem with
        # PythonRepos as a dependency.  Instead it does the minimum possible work to hand-roll
        # bootstrapping of the Subsystems it needs.
        known_scope_infos = [
            ksi
            for optionable in [GlobalOptionsRegistrar, PythonRepos]
            for ksi in optionable.known_scope_infos()
        ]
        options = self._options_bootstrapper.get_full_options(known_scope_infos)

        # Ignore command line flags since we'd blow up on any we don't understand (most of them).
        # If someone wants to bootstrap plugins in a one-off custom way they'll need to use env vars
        # or a --pants-config-files pointing to a custom pants.toml snippet.
        defaulted_only_options = options.drop_flag_values()

        # Finally, construct the Subsystem.
        return subsystem_type(options_scope, defaulted_only_options.for_scope(options_scope))
