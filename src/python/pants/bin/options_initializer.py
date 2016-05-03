# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import sys

import pkg_resources

from pants.base.build_environment import pants_version
from pants.base.exceptions import BuildConfigurationError
from pants.bin.extension_loader import load_plugins_and_backends
from pants.bin.plugin_resolver import PluginResolver
from pants.goal.goal import Goal
from pants.logging.setup import setup_logging
from pants.option.global_options import GlobalOptionsRegistrar
from pants.subsystem.subsystem import Subsystem


logger = logging.getLogger(__name__)


class OptionsInitializer(object):
  """Initializes global options and logging."""

  def __init__(self, options_bootstrapper, working_set=None, exiter=sys.exit, init_logging=True):
    """
    :param OptionsBootStrapper options_bootstrapper: An options bootstrapper instance.
    :param pkg_resources.WorkingSet working_set: The working set of the current run as returned by
                                                 PluginResolver.resolve().
    :param func exiter: A function that accepts an exit code value and exits (for tests).
    :param bool init_logging: Whether or not to initialize logging as part of options init.
    """
    self._options_bootstrapper = options_bootstrapper
    self._working_set = working_set or PluginResolver(self._options_bootstrapper).resolve()
    self._exiter = exiter
    self._init_logging = init_logging

  def _setup_logging(self, global_options):
    """Sets global logging."""
    # N.B. quiet help says 'Squelches all console output apart from errors'.
    level = 'ERROR' if global_options.quiet else global_options.level.upper()
    setup_logging(level, console_stream=sys.stderr, log_dir=global_options.logdir)

  def _register_options(self, subsystems, options):
    """Registers global options."""
    # Standalone global options.
    GlobalOptionsRegistrar.register_options_on_scope(options)

    # Options for subsystems.
    for subsystem in subsystems:
      subsystem.register_options_on_scope(options)

    # TODO(benjy): Should Goals or the entire goal-running mechanism be a Subsystem?
    for goal in Goal.all():
      # Register task options.
      goal.register_options(options)

  def _setup_options(self, options_bootstrapper, working_set):
    # TODO: This inline import is currently necessary to resolve a ~legitimate cycle between
    # `GoalRunner`->`EngineInitializer`->`OptionsInitializer`->`GoalRunner`.
    from pants.bin.goal_runner import GoalRunner

    bootstrap_options = options_bootstrapper.get_bootstrap_options()
    global_bootstrap_options = bootstrap_options.for_global_scope()

    if global_bootstrap_options.pants_version != pants_version():
      raise BuildConfigurationError(
        'Version mismatch: Requested version was {}, our version is {}.'.format(
          global_bootstrap_options.pants_version, pants_version()
        )
      )

    # Get logging setup prior to loading backends so that they can log as needed.
    if self._init_logging:
      self._setup_logging(global_bootstrap_options)

    # Add any extra paths to python path (e.g., for loading extra source backends).
    for path in global_bootstrap_options.pythonpath:
      sys.path.append(path)
      pkg_resources.fixup_namespace_packages(path)

    # Load plugins and backends.
    plugins = global_bootstrap_options.plugins
    backend_packages = global_bootstrap_options.backend_packages
    build_configuration = load_plugins_and_backends(plugins, working_set, backend_packages)

    # Now that plugins and backends are loaded, we can gather the known scopes.
    known_scope_infos = [GlobalOptionsRegistrar.get_scope_info()]

    # Add scopes for all needed subsystems via a union of all known subsystem sets.
    subsystems = Subsystem.closure(
      GoalRunner.subsystems() | Goal.subsystems() | build_configuration.subsystems()
    )
    for subsystem in subsystems:
      known_scope_infos.append(subsystem.get_scope_info())

    # Add scopes for all tasks in all goals.
    for goal in Goal.all():
      known_scope_infos.extend(filter(None, goal.known_scope_infos()))

    # Now that we have the known scopes we can get the full options.
    options = options_bootstrapper.get_full_options(known_scope_infos)
    self._register_options(subsystems, options)

    # Make the options values available to all subsystems.
    Subsystem.set_options(options)

    return options, build_configuration

  def setup(self):
    return self._setup_options(self._options_bootstrapper, self._working_set)
