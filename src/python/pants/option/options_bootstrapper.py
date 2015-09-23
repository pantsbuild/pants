# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os
import sys

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.config import Config
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.option_tracker import OptionTracker
from pants.option.option_util import is_boolean_flag
from pants.option.options import Options


class OptionsBootstrapper(object):
  """An object that knows how to create options in two stages: bootstrap, and then full options."""

  def __init__(self, env=None, configpath=None, args=None):
    self._env = env if env is not None else os.environ.copy()
    self._configpath = configpath
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
          elif is_boolean_flag(kwargs):
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

      configpaths = [self._configpath] if self._configpath else None
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
