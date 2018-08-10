# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import sys
from builtins import object

import pkg_resources

from pants.base.build_environment import pants_version
from pants.base.exceptions import BuildConfigurationError
from pants.goal.goal import Goal
from pants.init.extension_loader import load_backends_and_plugins
from pants.init.global_subsystems import GlobalSubsystems
from pants.init.plugin_resolver import PluginResolver
from pants.option.global_options import GlobalOptionsRegistrar
from pants.subsystem.subsystem import Subsystem


logger = logging.getLogger(__name__)


class BuildConfigInitializer(object):
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

  def _load_plugins(self, working_set, python_paths, plugins, backend_packages):
    # Add any extra paths to python path (e.g., for loading extra source backends).
    for path in python_paths:
      if path not in sys.path:
        sys.path.append(path)
        pkg_resources.fixup_namespace_packages(path)

    # Load plugins and backends.
    return load_backends_and_plugins(plugins, working_set, backend_packages)

  def setup(self):
    """Load backends and plugins.

    :returns: A `BuildConfiguration` object constructed during backend/plugin loading.
    """
    return self._load_plugins(
      self._working_set,
      self._bootstrap_options.pythonpath,
      self._bootstrap_options.plugins,
      self._bootstrap_options.backend_packages
    )


class OptionsInitializer(object):
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
      {GlobalOptionsRegistrar} |
      GlobalSubsystems.get() |
      build_configuration.subsystems() |
      set(Goal.get_optionables())
    )

    known_scope_infos = sorted({
      si for optionable in top_level_optionables for si in optionable.known_scope_infos()
    })

    # Now that we have the known scopes we can get the full options.
    options = options_bootstrapper.get_full_options(known_scope_infos)

    distinct_optionable_classes = sorted({si.optionable_cls for si in known_scope_infos},
                                         key=lambda o: o.options_scope)
    for optionable_cls in distinct_optionable_classes:
      optionable_cls.register_options_on_scope(options)

    return options

  @classmethod
  def create(cls, options_bootstrapper, build_configuration, init_subsystems=True):
    global_bootstrap_options = options_bootstrapper.get_bootstrap_options().for_global_scope()

    if global_bootstrap_options.pants_version != pants_version():
      raise BuildConfigurationError(
        'Version mismatch: Requested version was {}, our version is {}.'
        .format(global_bootstrap_options.pants_version, pants_version())
      )

    # Parse and register options.
    options = cls._construct_options(options_bootstrapper, build_configuration)

    GlobalOptionsRegistrar.validate_instance(options.for_global_scope())

    if init_subsystems:
      Subsystem.set_options(options)

    return options
