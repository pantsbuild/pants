# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os
import sys

from pants.base.config import Config
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.option_util import is_boolean_flag
from pants.option.options import Options


class OptionsBootstrapper(object):
  """An object that knows how to create options in two stages: bootstrap, and then full options."""
  def __init__(self, env=None, configpath=None, args=None):
    self._env = env or os.environ.copy()
    self._configpath = configpath
    self._post_bootstrap_config = None  # Will be set later.
    self._args = args or sys.argv
    self._bootstrap_options = None  # We memoize the bootstrap options here.
    self._full_options = None  # We memoize the full options here.

  def get_bootstrap_options(self):
    """:returns: an Options instance that only knows about the bootstrap options.
    :rtype: Options
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
        bootstrap_options = Options(env=self._env, config=config,
            known_scope_infos=[GlobalOptionsRegistrar.get_scope_info()], args=bargs)
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
        full_configpaths.append(bootstrap_option_values.config_override)
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
    """Get the full Options instance bootstrapped by this object.

    :param known_scope_infos: ScopeInfos for all scopes that may be encountered.
    """
    if not self._full_options:
      # Note: Don't inline this into the Options() call, as this populates
      # self._post_bootstrap_config, which is another argument to that call.
      bootstrap_options = self.get_bootstrap_options()
      self._full_options = Options(self._env,
                                   self._post_bootstrap_config,
                                   known_scope_infos,
                                   args=self._args,
                                   bootstrap_option_values=bootstrap_options.for_global_scope())
    return self._full_options
