# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import sys
from typing import Optional, Tuple

import pkg_resources

from pants.base.build_environment import pants_version
from pants.base.exceptions import BuildConfigurationError
from pants.build_graph.build_configuration import BuildConfiguration
from pants.init.extension_loader import load_backends_and_plugins
from pants.init.plugin_resolver import PluginResolver
from pants.option.global_options import GlobalOptions
from pants.option.option_value_container import OptionValueContainer
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.subsystem import Subsystem
from pants.util.dirutil import fast_relpath_optional
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


class BuildConfigInitializer:
    """Initializes a BuildConfiguration object.

    This class uses a class-level cache for the internally generated `BuildConfiguration` object,
    which permits multiple invocations in the same runtime context without re-incurring backend &
    plugin loading, which can be expensive and cause issues (double task registration, etc).
    """

    _cached_build_config: Optional[BuildConfiguration] = None

    @classmethod
    def get(cls, options_bootstrapper: OptionsBootstrapper) -> BuildConfiguration:
        if cls._cached_build_config is None:
            cls._cached_build_config = cls(options_bootstrapper).setup()
        return cls._cached_build_config

    @classmethod
    def reset(cls) -> None:
        cls._cached_build_config = None

    def __init__(self, options_bootstrapper: OptionsBootstrapper) -> None:
        self._bootstrap_options = options_bootstrapper.get_bootstrap_options().for_global_scope()
        self._working_set = PluginResolver(options_bootstrapper).resolve()

    def setup(self) -> BuildConfiguration:
        """Loads backends and plugins."""

        # Add any extra paths to python path (e.g., for loading extra source backends).
        for path in self._bootstrap_options.pythonpath:
            if path not in sys.path:
                sys.path.append(path)
                pkg_resources.fixup_namespace_packages(path)

        # Load plugins and backends.
        return load_backends_and_plugins(
            self._bootstrap_options.plugins,
            self._working_set,
            self._bootstrap_options.backend_packages,
        )


class OptionsInitializer:
    """Initializes options."""

    @staticmethod
    def compute_pants_ignore(buildroot, global_options):
        """Computes the merged value of the `--pants-ignore` flag.

        This inherently includes the workdir and distdir locations if they are located under the
        buildroot.
        """
        pants_ignore = list(global_options.pants_ignore)

        def add(absolute_path, include=False):
            # To ensure that the path is ignored regardless of whether it is a symlink or a directory, we
            # strip trailing slashes (which would signal that we wanted to ignore only directories).
            maybe_rel_path = fast_relpath_optional(absolute_path, buildroot)
            if maybe_rel_path:
                rel_path = maybe_rel_path.rstrip(os.path.sep)
                prefix = "!" if include else ""
                pants_ignore.append(f"{prefix}/{rel_path}")

        add(global_options.pants_workdir)
        add(global_options.pants_distdir)
        add(global_options.pants_subprocessdir)

        return pants_ignore

    @staticmethod
    def compute_pantsd_invalidation_globs(
        buildroot: str, bootstrap_options: OptionValueContainer
    ) -> Tuple[str, ...]:
        """Computes the merged value of the `--pantsd-invalidation-globs` option.

        Combines --pythonpath and --pants-config-files files that are in {buildroot} dir with those
        invalidation_globs provided by users.
        """
        invalidation_globs: OrderedSet[str] = OrderedSet()

        # Globs calculated from the sys.path and other file-like configuration need to be sanitized
        # to relative globs (where possible).
        potentially_absolute_globs = (
            *sys.path,
            *bootstrap_options.pythonpath,
            *bootstrap_options.pants_config_files,
        )
        for glob in potentially_absolute_globs:
            # NB: We use `relpath` here because these paths are untrusted, and might need to be
            # normalized in addition to being relativized.
            glob_relpath = os.path.relpath(glob, buildroot)
            if glob_relpath == "." or glob_relpath.startswith(".."):
                logger.debug(
                    f"Changes to {glob}, outside of the buildroot, will not be invalidated."
                )
            else:
                invalidation_globs.update([glob_relpath, glob_relpath + "/**"])

        # Explicitly specified globs are already relative, and are added verbatim.
        invalidation_globs.update(
            (
                "!*.pyc",
                "!__pycache__/",
                # TODO: This is a bandaid for https://github.com/pantsbuild/pants/issues/7022:
                # macros should be adapted to allow this dependency to be automatically detected.
                "requirements.txt",
                "3rdparty/**/requirements.txt",
                *bootstrap_options.pantsd_invalidation_globs,
            )
        )

        return tuple(invalidation_globs)

    @classmethod
    def create(
        cls,
        options_bootstrapper: OptionsBootstrapper,
        build_configuration: BuildConfiguration,
        init_subsystems: bool = True,
    ) -> Options:
        global_bootstrap_options = options_bootstrapper.get_bootstrap_options().for_global_scope()

        if global_bootstrap_options.pants_version != pants_version():
            raise BuildConfigurationError(
                f"Version mismatch: Requested version was {global_bootstrap_options.pants_version}, "
                f"our version is {pants_version()}."
            )

        # Parse and register options.

        known_scope_infos = [
            si
            for optionable in build_configuration.all_optionables
            for si in optionable.known_scope_infos()
        ]
        options = options_bootstrapper.get_full_options(known_scope_infos)

        GlobalOptions.validate_instance(options.for_global_scope())

        if init_subsystems:
            Subsystem.set_options(options)

        return options
