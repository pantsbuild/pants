# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import logging
import sys
from contextlib import contextmanager
from typing import Iterator, Tuple

import pkg_resources

from pants.build_graph.build_configuration import BuildConfiguration
from pants.help.flag_error_help_printer import FlagErrorHelpPrinter
from pants.init.extension_loader import load_backends_and_plugins
from pants.init.plugin_resolver import PluginResolver
from pants.option.errors import UnknownFlagsError
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper

logger = logging.getLogger(__name__)


def _initialize_build_configuration(
    options_bootstrapper: OptionsBootstrapper,
) -> BuildConfiguration:
    """Initialize a BuildConfiguration for the given OptionsBootstrapper.

    NB: This method:
      1. has the side-effect of (idempotently) adding PYTHONPATH entries for this process
      2. is expensive to call, because it might resolve plugins from the network
    """

    bootstrap_options = options_bootstrapper.get_bootstrap_options().for_global_scope()
    working_set = PluginResolver(options_bootstrapper).resolve()

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


class OptionsInitializer:
    """Initializes BuildConfiguration and Options instances."""

    @classmethod
    def create_with_build_config(
        cls, options_bootstrapper: OptionsBootstrapper, *, raise_: bool
    ) -> Tuple[BuildConfiguration, Options]:
        build_config = _initialize_build_configuration(options_bootstrapper)
        with OptionsInitializer.handle_unknown_flags(options_bootstrapper, raise_=raise_):
            options = options_bootstrapper.full_options(build_config)
        return build_config, options

    @classmethod
    @contextmanager
    def handle_unknown_flags(
        cls, options_bootstrapper: OptionsBootstrapper, *, raise_: bool
    ) -> Iterator[None]:
        """If there are any unknown flags, print "Did you mean?" and possibly error."""
        try:
            yield
        except UnknownFlagsError as err:
            build_config = _initialize_build_configuration(options_bootstrapper)
            # We need an options instance in order to get "did you mean" suggestions, but we know
            # there are bad flags in the args, so we generate options with no flags.
            no_arg_bootstrapper = dataclasses.replace(
                options_bootstrapper, args=("dummy_first_arg",)
            )
            options = no_arg_bootstrapper.full_options(build_config)
            FlagErrorHelpPrinter(options).handle_unknown_flags(err)
            if raise_:
                raise err
