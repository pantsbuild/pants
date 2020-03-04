# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import re
import sys

import pkg_resources

from pants.base.build_environment import pants_version
from pants.base.exceptions import BuildConfigurationError
from pants.build_graph.build_configuration import BuildConfiguration
from pants.goal.goal import Goal
from pants.init.extension_loader import load_backends_and_plugins
from pants.init.global_subsystems import GlobalSubsystems
from pants.init.plugin_resolver import PluginResolver
from pants.option.global_options import GlobalOptions
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import fast_relpath_optional

logger = logging.getLogger(__name__)


class BuildConfigInitializer:
    """Initializes a BuildConfiguration object.

    This class uses a class-level cache for the internally generated `BuildConfiguration` object,
    which permits multiple invocations in the same runtime context without re-incurring backend &
    plugin loading, which can be expensive and cause issues (double task registration, etc).
    """

    _cached_build_config = None

    @classmethod
    def get(cls, options_bootstrapper):
        if cls._cached_build_config is None:
            cls._cached_build_config = cls(options_bootstrapper).setup()
        return cls._cached_build_config

    @classmethod
    def reset(cls):
        cls._cached_build_config = None

    def __init__(self, options_bootstrapper):
        self._options_bootstrapper = options_bootstrapper
        self._bootstrap_options = options_bootstrapper.get_bootstrap_options().for_global_scope()
        self._working_set = PluginResolver(self._options_bootstrapper).resolve()

    def _load_plugins(self):
        # Add any extra paths to python path (e.g., for loading extra source backends).
        for path in self._bootstrap_options.pythonpath:
            if path not in sys.path:
                sys.path.append(path)
                pkg_resources.fixup_namespace_packages(path)

        # Load plugins and backends.
        return load_backends_and_plugins(
            self._bootstrap_options.plugins,
            self._bootstrap_options.plugins2,
            self._working_set,
            self._bootstrap_options.backend_packages,
            self._bootstrap_options.backend_packages2,
            BuildConfiguration(),
        )

    def setup(self):
        """Load backends and plugins.

        :returns: A `BuildConfiguration` object constructed during backend/plugin loading.
        """
        return self._load_plugins()


class OptionsInitializer:
    """Initializes options."""

    @staticmethod
    def _construct_options(options_bootstrapper, build_configuration):
        """Parse and register options.

        :returns: An Options object representing the full set of runtime options.
        """
        # Now that plugins and backends are loaded, we can gather the known scopes.

        # Gather the optionables that are not scoped to any other.  All known scopes are reachable
        # via these optionables' known_scope_infos() methods.
        top_level_optionables = (
            {GlobalOptions}
            | GlobalSubsystems.get()
            | build_configuration.optionables()
            | set(Goal.get_optionables())
        )

        # Now that we have the known scopes we can get the full options. `get_full_options` will
        # sort and de-duplicate these for us.
        known_scope_infos = [
            si for optionable in top_level_optionables for si in optionable.known_scope_infos()
        ]
        return options_bootstrapper.get_full_options(known_scope_infos)

    @staticmethod
    def compute_pants_ignore(buildroot, global_options):
        """Computes the merged value of the `--pants-ignore` flag.

        This inherently includes the workdir and distdir locations if they are located under the
        buildroot.
        """
        pants_ignore = list(global_options.pants_ignore)

        def add_ignore(absolute_path):
            # To ensure that the path is ignored regardless of whether it is a symlink or a directory, we
            # strip trailing slashes (which would signal that we wanted to ignore only directories).
            maybe_rel_path = fast_relpath_optional(absolute_path, buildroot)
            # Exclude temp workdir from <pants_ignore>.
            # temp workdir is /path/to/<pants_workdir>/tmp/tmp<process_id>.pants.d
            if maybe_rel_path and not re.search("tmp/tmp(.+).pants.d", maybe_rel_path):
                rel_path = maybe_rel_path.rstrip(os.path.sep)
                pants_ignore.append(f"/{rel_path}")

        add_ignore(global_options.pants_workdir)
        add_ignore(global_options.pants_distdir)
        return pants_ignore

    @staticmethod
    def compute_pantsd_invalidation_globs(buildroot, bootstrap_options):
        """Computes the merged value of the `--pantsd-invalidation-globs` option.

        Combines --pythonpath and --pants-config-files files that are in {buildroot} dir with those
        invalidation_globs provided by users.
        """
        invalidation_globs = []
        globs = (
            bootstrap_options.pythonpath
            + bootstrap_options.pants_config_files
            + bootstrap_options.pantsd_invalidation_globs
        )

        for glob in globs:
            glob_relpath = os.path.relpath(glob, buildroot)
            if glob_relpath and (not glob_relpath.startswith("../")):
                invalidation_globs.extend([glob_relpath, glob_relpath + "/**"])
            else:
                logging.getLogger(__name__).warning(
                    f"Changes to {glob}, outside of the buildroot, will not be invalidated."
                )

        return invalidation_globs

    @classmethod
    def create(cls, options_bootstrapper, build_configuration, init_subsystems=True):
        global_bootstrap_options = options_bootstrapper.get_bootstrap_options().for_global_scope()

        if global_bootstrap_options.pants_version != pants_version():
            raise BuildConfigurationError(
                f"Version mismatch: Requested version was {global_bootstrap_options.pants_version}, "
                f"our version is {pants_version()}."
            )

        # Parse and register options.
        options = cls._construct_options(options_bootstrapper, build_configuration)

        GlobalOptions.validate_instance(options.for_global_scope())

        if init_subsystems:
            Subsystem.set_options(options)

        return options
