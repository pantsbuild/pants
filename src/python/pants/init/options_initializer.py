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
from pants.goal.goal import Goal
from pants.init.extension_loader import load_backends_and_plugins
from pants.init.plugin_resolver import PluginResolver
from pants.logging.setup import setup_logging
from pants.option.global_options import GlobalOptionsRegistrar
from pants.subsystem.subsystem import Subsystem


logger = logging.getLogger(__name__)


class OptionsInitializer(object):
  """Initializes backends/plugins, global options and logging.

  This class uses a class-level cache for the internally generated `BuildConfiguration` object,
  which permits multiple invocations in the same runtime context without re-incurring backend &
  plugin loading, which can be expensive and cause issues (double task registration, etc).
  """

  # Class-level cache for the `BuildConfiguration` object.
  _build_configuration = None

  def __init__(self, options_bootstrapper, working_set=None, exiter=sys.exit):
    """
    :param OptionsBootStrapper options_bootstrapper: An options bootstrapper instance.
    :param pkg_resources.WorkingSet working_set: The working set of the current run as returned by
                                                 PluginResolver.resolve().
    :param func exiter: A function that accepts an exit code value and exits (for tests).
    """
    self._options_bootstrapper = options_bootstrapper
    self._working_set = working_set or PluginResolver(self._options_bootstrapper).resolve()
    self._exiter = exiter

  @classmethod
  def _has_build_configuration(cls):
    return cls._build_configuration is not None

  @classmethod
  def _get_build_configuration(cls):
    return cls._build_configuration

  @classmethod
  def _set_build_configuration(cls, build_configuration):
    cls._build_configuration = build_configuration

  @classmethod
  def reset(cls):
    cls._set_build_configuration(None)

  def _setup_logging(self, quiet, level, log_dir):
    """Initializes logging."""
    # N.B. quiet help says 'Squelches all console output apart from errors'.
    level = 'ERROR' if quiet else level.upper()
    setup_logging(level, console_stream=sys.stderr, log_dir=log_dir)

  def _load_plugins(self, working_set, python_paths, plugins, backend_packages):
    """Load backends and plugins.

    :returns: A `BuildConfiguration` object constructed during backend/plugin loading.
    """
    # Add any extra paths to python path (e.g., for loading extra source backends).
    for path in python_paths:
      if path not in sys.path:
        sys.path.append(path)
        pkg_resources.fixup_namespace_packages(path)

    # Load plugins and backends.
    return load_backends_and_plugins(plugins, working_set, backend_packages)

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

  def _install_options(self, options_bootstrapper, build_configuration):
    """Parse and register options.

    :returns: An Options object representing the full set of runtime options.
    """
    # TODO: This inline import is currently necessary to resolve a ~legitimate cycle between
    # `GoalRunner`->`EngineInitializer`->`OptionsInitializer`->`GoalRunner`.
    from pants.bin.goal_runner import GoalRunner

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

    return options

  def setup(self, init_logging=True):
    """Initializes logging, loads backends/plugins and parses options.

    :param bool init_logging: Whether or not to initialize logging as part of setup.
    :returns: A tuple of (options, build_configuration).
    """
    global_bootstrap_options = self._options_bootstrapper.get_bootstrap_options().for_global_scope()

    if global_bootstrap_options.pants_version != pants_version():
      raise BuildConfigurationError(
        'Version mismatch: Requested version was {}, our version is {}.'
        .format(global_bootstrap_options.pants_version, pants_version())
      )

    # Get logging setup prior to loading backends so that they can log as needed.
    if init_logging:
      self._setup_logging(global_bootstrap_options.quiet,
                          global_bootstrap_options.level,
                          global_bootstrap_options.logdir)

    # Conditionally load backends/plugins and materialize a `BuildConfiguration` object.
    if not self._has_build_configuration():
      build_configuration = self._load_plugins(self._working_set,
                                               global_bootstrap_options.pythonpath,
                                               global_bootstrap_options.plugins,
                                               global_bootstrap_options.backend_packages)
      self._set_build_configuration(build_configuration)
    else:
      build_configuration = self._get_build_configuration()

    # Parse and register options.
    options = self._install_options(self._options_bootstrapper, build_configuration)

    return options, build_configuration
