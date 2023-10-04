# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import importlib
import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List

import pkg_resources

from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.internals.native_engine import PyExecutor
from pants.engine.unions import UnionMembership
from pants.help.flag_error_help_printer import FlagErrorHelpPrinter
from pants.init.bootstrap_scheduler import BootstrapScheduler
from pants.init.engine_initializer import EngineInitializer
from pants.init.extension_loader import (
    load_backends_and_plugins,
    load_build_configuration_from_source,
)
from pants.init.plugin_resolver import PluginResolver
from pants.init.plugin_resolver import rules as plugin_resolver_rules
from pants.option.errors import UnknownFlagsError
from pants.option.global_options import DynamicRemoteOptions
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.requirements import parse_requirements_file

logger = logging.getLogger(__name__)


def _initialize_build_configuration(
    plugin_resolver: PluginResolver,
    options_bootstrapper: OptionsBootstrapper,
    env: CompleteEnvironmentVars,
) -> BuildConfiguration:
    """Initialize a BuildConfiguration for the given OptionsBootstrapper.

    NB: This method:
      1. has the side-effect of (idempotently) adding PYTHONPATH entries for this process
      2. is expensive to call, because it might resolve plugins from the network
    """

    bootstrap_options = options_bootstrapper.get_bootstrap_options().for_global_scope()
    backends_requirements = _collect_backends_requirements(bootstrap_options.backend_packages)
    working_set = plugin_resolver.resolve(options_bootstrapper, env, backends_requirements)

    # Add any extra paths to python path (e.g., for loading extra source backends).
    for path in bootstrap_options.pythonpath:
        if path not in sys.path:
            sys.path.append(path)
            pkg_resources.fixup_namespace_packages(path)

    # Load plugins and backends.
    return load_backends_and_plugins(
        bootstrap_options.plugins,
        working_set,
        bootstrap_options.backend_packages,
    )


def _collect_backends_requirements(backends: List[str]) -> List[str]:
    """Collects backend package dependencies, in case those are declared in an adjacent
    requirements.txt. Ignores any loading errors, assuming those will be later on handled by the
    backends loader.

    :param backends: An list of packages to load v2 backends requirements from.
    """
    requirements = []

    for backend_package in backends:
        try:
            backend_package_spec = importlib.util.find_spec(backend_package)
        except ModuleNotFoundError:
            continue

        if backend_package_spec is None:
            continue

        if backend_package_spec.origin is None:
            logger.warning(
                f"Can not check requirements for backend: '{backend_package}'. A __init__.py file is probably missing."
            )
            continue

        requirements_txt_file_path = Path(backend_package_spec.origin).parent.joinpath(
            "requirements.txt"
        )
        if requirements_txt_file_path.exists():
            content = requirements_txt_file_path.read_text()
            backend_package_requirements = [
                str(r)
                for r in parse_requirements_file(content, rel_path=str(requirements_txt_file_path))
            ]
            requirements.extend(backend_package_requirements)

    return requirements


def create_bootstrap_scheduler(
    options_bootstrapper: OptionsBootstrapper, executor: PyExecutor
) -> BootstrapScheduler:
    bc_builder = BuildConfiguration.Builder()
    # To load plugins, we only need access to the Python/PEX rules.
    load_build_configuration_from_source(bc_builder, ["pants.backend.python"])
    # And to plugin-loading-specific rules.
    bc_builder.register_rules("_dummy_for_bootstrapping_", plugin_resolver_rules())
    # We allow unrecognized options to defer any option error handling until post-bootstrap.
    bc_builder.allow_unknown_options()
    return BootstrapScheduler(
        EngineInitializer.setup_graph(
            options_bootstrapper.bootstrap_options.for_global_scope(),
            bc_builder.create(),
            DynamicRemoteOptions.disabled(),
            executor,
            is_bootstrap=True,
        ).scheduler
    )


class OptionsInitializer:
    """Initializes BuildConfiguration and Options instances given an OptionsBootstrapper.

    NB: Although this constructor takes an instance of the OptionsBootstrapper, it is
    used only to construct a "bootstrap" Scheduler: actual calls to resolve plugins use a
    per-request instance of the OptionsBootstrapper, which might request different plugins.

    TODO: We would eventually like to use the bootstrap Scheduler to construct the
    OptionsBootstrapper as well, but for now we do the opposite thing, and the Scheduler is
    used only to resolve plugins.
      see: https://github.com/pantsbuild/pants/issues/10360
    """

    def __init__(
        self,
        options_bootstrapper: OptionsBootstrapper,
        executor: PyExecutor,
    ) -> None:
        self._bootstrap_scheduler = create_bootstrap_scheduler(options_bootstrapper, executor)
        self._plugin_resolver = PluginResolver(self._bootstrap_scheduler)

    def build_config(
        self,
        options_bootstrapper: OptionsBootstrapper,
        env: CompleteEnvironmentVars,
    ) -> BuildConfiguration:
        return _initialize_build_configuration(self._plugin_resolver, options_bootstrapper, env)

    def options(
        self,
        options_bootstrapper: OptionsBootstrapper,
        env: CompleteEnvironmentVars,
        build_config: BuildConfiguration,
        union_membership: UnionMembership,
        *,
        raise_: bool,
    ) -> Options:
        with self.handle_unknown_flags(options_bootstrapper, env, raise_=raise_):
            return options_bootstrapper.full_options(build_config, union_membership)

    @contextmanager
    def handle_unknown_flags(
        self,
        options_bootstrapper: OptionsBootstrapper,
        env: CompleteEnvironmentVars,
        *,
        raise_: bool,
    ) -> Iterator[None]:
        """If there are any unknown flags, print "Did you mean?" and possibly error."""
        try:
            yield
        except UnknownFlagsError as err:
            build_config = _initialize_build_configuration(
                self._plugin_resolver, options_bootstrapper, env
            )
            # We need an options instance in order to get "did you mean" suggestions, but we know
            # there are bad flags in the args, so we generate options with no flags.
            no_arg_bootstrapper = dataclasses.replace(
                options_bootstrapper, args=("dummy_first_arg",)
            )
            options = no_arg_bootstrapper.full_options(
                build_config,
                union_membership=UnionMembership({}),
            )
            FlagErrorHelpPrinter(options).handle_unknown_flags(err)
            if raise_:
                raise err
