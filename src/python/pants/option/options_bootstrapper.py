# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import logging
import os
import sys

from pants.base.build_environment import get_default_pants_config_file
from pants.option.arg_splitter import GLOBAL_SCOPE, GLOBAL_SCOPE_CONFIG_SECTION
from pants.option.config import Config
from pants.option.custom_types import ListValueComponent
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.option_tracker import OptionTracker
from pants.option.options import Options


logger = logging.getLogger(__name__)


class OptionsBootstrapper(object):
  """An object that knows how to create options in two stages: bootstrap, and then full options."""

  @staticmethod
  def get_config_file_paths(env, args):
    """Get the location of the config files.

    The locations are specified by the --pants-config-files option.  However we need to load the
    config in order to process the options.  This method special-cases --pants-config-files
    in order to solve this chicken-and-egg problem.

    Note that, obviously, it's not possible to set the location of config files in a config file.
    Doing so will have no effect.
    """
    # This exactly mirrors the logic applied in Option to all regular options.  Note that we'll
    # also parse --pants-config as a regular option later, but there's no harm in that.  In fact,
    # it's preferable, so that any code that happens to want to know where we read config from
    # can inspect the option.
    flag = '--pants-config-files='
    evars = ['PANTS_GLOBAL_PANTS_CONFIG_FILES', 'PANTS_PANTS_CONFIG_FILES', 'PANTS_CONFIG_FILES']

    path_list_values = [ListValueComponent.create(get_default_pants_config_file())]
    for var in evars:
      if var in env:
        path_list_values.append(ListValueComponent.create(env[var]))
        break

    for arg in args:
      # Technically this is very slightly incorrect, as we don't check scope.  But it's
      # very unlikely that any task or subsystem will have an option named --pants-config-files.
      # TODO: Enforce a ban on options with a --pants- prefix outside our global options?
      if arg.startswith(flag):
        path_list_values.append(ListValueComponent.create(arg[len(flag):]))

    return ListValueComponent.merge(path_list_values).val

  def __init__(self, env=None, args=None):
    self._env = env if env is not None else os.environ.copy()
    self._post_bootstrap_config = None  # Will be set later.
    self._args = sys.argv if args is None else args
    self._bootstrap_options = None  # We memoize the bootstrap options here.
    self._full_options = {}  # We memoize the full options here.
    self._option_tracker = OptionTracker()

  def get_bootstrap_options(self):
    """:returns: an Options instance that only knows about the bootstrap options.
    :rtype: :class:`Options`
    """
    if not self._bootstrap_options:
      flags = set()
      short_flags = set()

      def capture_the_flags(*args, **kwargs):
        for arg in args:
          flags.add(arg)
          if len(arg) == 2:
            short_flags.add(arg)
          elif kwargs.get('type') == bool:
            flags.add('--no-{}'.format(arg[2:]))

      GlobalOptionsRegistrar.register_bootstrap_options(capture_the_flags)

      def is_bootstrap_option(arg):
        components = arg.split('=', 1)
        if components[0] in flags:
          return True
        for flag in short_flags:
          if arg.startswith(flag):
            return True
        return False

      # Take just the bootstrap args, so we don't choke on other global-scope args on the cmd line.
      # Stop before '--' since args after that are pass-through and may have duplicate names to our
      # bootstrap options.
      bargs = filter(is_bootstrap_option, itertools.takewhile(lambda arg: arg != '--', self._args))

      configpaths = self.get_config_file_paths(env=self._env, args=self._args)
      pre_bootstrap_config = Config.load(configpaths)

      def bootstrap_options_from_config(config):
        bootstrap_options = Options.create(env=self._env, config=config,
            known_scope_infos=[GlobalOptionsRegistrar.get_scope_info()], args=bargs,
            option_tracker=self._option_tracker)

        def register_global(*args, **kwargs):
          bootstrap_options.register(GLOBAL_SCOPE, *args, **kwargs)
        GlobalOptionsRegistrar.register_bootstrap_options(register_global)
        return bootstrap_options

      initial_bootstrap_options = bootstrap_options_from_config(pre_bootstrap_config)
      bootstrap_option_values = initial_bootstrap_options.for_global_scope()

      # Now re-read the config, post-bootstrapping. Note the order: First whatever we bootstrapped
      # from (typically pants.ini), then config override, then rcfiles.
      full_configpaths = pre_bootstrap_config.sources()
      if bootstrap_option_values.config_override:
        full_configpaths.extend(bootstrap_option_values.config_override)

      if bootstrap_option_values.pantsrc:
        rcfiles = [os.path.expanduser(rcfile) for rcfile in bootstrap_option_values.pantsrc_files]
        existing_rcfiles = filter(os.path.exists, rcfiles)
        full_configpaths.extend(existing_rcfiles)

      self._post_bootstrap_config = Config.load(full_configpaths,
                                                seed_values=bootstrap_option_values)

      # Now recompute the bootstrap options with the full config. This allows us to pick up
      # bootstrap values (such as backends) from a config override file, for example.
      self._bootstrap_options = bootstrap_options_from_config(self._post_bootstrap_config)
    return self._bootstrap_options

  def get_full_options(self, known_scope_infos):
    """Get the full Options instance bootstrapped by this object for the given known scopes.

    :param known_scope_infos: ScopeInfos for all scopes that may be encountered.
    :returns: A bootrapped Options instance that also carries options for all the supplied known
              scopes.
    :rtype: :class:`Options`
    """
    key = frozenset(sorted(known_scope_infos))
    if key not in self._full_options:
      # Note: Don't inline this into the Options() call, as this populates
      # self._post_bootstrap_config, which is another argument to that call.
      bootstrap_option_values = self.get_bootstrap_options().for_global_scope()
      self._full_options[key] = Options.create(self._env,
                                               self._post_bootstrap_config,
                                               known_scope_infos,
                                               args=self._args,
                                               bootstrap_option_values=bootstrap_option_values,
                                               option_tracker=self._option_tracker)
    return self._full_options[key]

  def verify_configs_against_options(self, options):
    """Verify all loaded configs have correct scopes and options.

    :param options: Fully bootstrapped valid options.
    :return: None.
    """
    error_log = []
    for config in self._post_bootstrap_config.configs():
      for section in config.sections():
        if section == GLOBAL_SCOPE_CONFIG_SECTION:
          scope = GLOBAL_SCOPE
        else:
          scope = section
        try:
          valid_options_under_scope = set(options.for_scope(scope))
        # Only catch ConfigValidationError. Other exceptions will be raised directly.
        except Config.ConfigValidationError:
          error_log.append("Invalid scope [{}] in {}".format(section, config.configpath))
        else:
          # All the options specified under [`section`] in `config` excluding bootstrap defaults.
          all_options_under_scope = (set(config.configparser.options(section)) -
                                     set(config.configparser.defaults()))
          for option in all_options_under_scope:
            if option not in valid_options_under_scope:
              error_log.append("Invalid option '{}' under [{}] in {}".format(option, section, config.configpath))

    if error_log:
      for error in error_log:
        logger.error(error)
      raise Config.ConfigValidationError("Invalid config entries detected. "
                              "See log for details on which entries to update or remove.\n"
                              "(Specify --no-verify-config to disable this check.)")
