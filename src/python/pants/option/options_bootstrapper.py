# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import logging
import os
import sys

from pants.base.build_environment import get_buildroot, get_pants_cachedir, get_pants_configdir
from pants.base.config import Config
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.options import Options
from pants.option.parser import Parser


def register_bootstrap_options(register, buildroot=None):
  """Register bootstrap options.

  "Bootstrap options" are a small set of options whose values are useful when registering other
  options. Therefore we must bootstrap them early, before other options are registered, let
  alone parsed.

  Bootstrap option values can be interpolated into the config file, and can be referenced
  programatically in registration code, e.g., as register.bootstrap.pants_workdir.

  Note that regular code can also access these options as normal global-scope options. Their
  status as "bootstrap options" is only pertinent during option registration.
  """
  buildroot = buildroot or get_buildroot()
  register('--pants-bootstrapdir', advanced=True, metavar='<dir>', default=get_pants_cachedir(),
           help='Use this dir for global cache.')
  register('--pants-configdir', advanced=True, metavar='<dir>', default=get_pants_configdir(),
         help='Use this dir for global config files.')
  register('--pants-workdir', metavar='<dir>', default=os.path.join(buildroot, '.pants.d'),
           help='Write intermediate output files to this dir.')
  register('--pants-supportdir', metavar='<dir>', default=os.path.join(buildroot, 'build-support'),
           help='Use support files from this dir.')
  register('--pants-distdir', metavar='<dir>', default=os.path.join(buildroot, 'dist'),
           help='Write end-product artifacts to this dir.')
  register('--config-override', help='A second config file, to override pants.ini.')
  register('--pantsrc', action='store_true', default=True,
           help='Use pantsrc files.')
  register('--pantsrc-files', action='append', metavar='<path>',
           default=['/etc/pantsrc', '~/.pants.rc'],
           help='Override config with values from these files. Later files override earlier ones.')
  register('--pythonpath', action='append',
           help='Add these directories to PYTHONPATH to search for plugins.')
  register('--target-spec-file', action='append', dest='target_spec_files',
           help='Read additional specs from this file, one per line')

  # These logging options are registered in the bootstrap phase so that plugins can log during
  # registration and not so that their values can be interpolated in configs.
  register('-d', '--logdir', metavar='<dir>',
           help='Write logs to files under this directory.')

  # Although logging supports the WARN level, its not documented and could conceivably be yanked.
  # Since pants has supported 'warn' since inception, leave the 'warn' choice as-is but explicitly
  # setup a 'WARN' logging level name that maps to 'WARNING'.
  logging.addLevelName(logging.WARNING, 'WARN')
  register('-l', '--level', choices=['debug', 'info', 'warn'], default='info', recursive=True,
           help='Set the logging level.')

  register('-q', '--quiet', action='store_true',
           help='Squelches all console output apart from errors.')


class OptionsBootstrapper(object):
  """An object that knows how to create options in two stages: bootstrap, and then full options."""
  def __init__(self, env=None, configpath=None, args=None, buildroot=None):
    self._buildroot = buildroot or get_buildroot()
    self._env = env or os.environ.copy()
    Config.reset_default_bootstrap_option_values(buildroot=self._buildroot)
    self._pre_bootstrap_config = Config.load([configpath] if configpath else None)
    self._post_bootstrap_config = None  # Will be set later.
    self._args = args or sys.argv
    self._bootstrap_options = None  # We memoize the bootstrap options here.
    self._full_options = None  # We memoize the full options here.
    # So other startup code has config to work with. This will go away once we replace direct
    # config accesses with options, and plumb those through everywhere that needs them.
    Config.cache(self._pre_bootstrap_config)

  def get_bootstrap_options(self):
    """:returns: an Options instance that only knows about the bootstrap options.
    :rtype: Options
    """
    if not self._bootstrap_options:
      flags = set()
      short_flags = set()

      def capture_the_flags(*args, **kwargs):
        for flag in Parser.expand_flags(*args, **kwargs):
          flags.add(flag.name)
          if len(flag.name) == 2:
            short_flags.add(flag.name)
          if flag.inverse_name:
            flags.add(flag.inverse_name)

      register_bootstrap_options(capture_the_flags, buildroot=self._buildroot)

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

      self._bootstrap_options = Options(env=self._env, config=self._pre_bootstrap_config,
                                        known_scopes=[GLOBAL_SCOPE], args=bargs)
      register_bootstrap_options(self._bootstrap_options.register_global, buildroot=self._buildroot)
      bootstrap_option_values = self._bootstrap_options.for_global_scope()
      Config.reset_default_bootstrap_option_values(values=bootstrap_option_values)

      # Now re-read the config, post-bootstrapping. Note the order: First whatever we bootstrapped
      # from (typically pants.ini), then config override, then rcfiles.
      configpaths = list(self._pre_bootstrap_config.sources())
      if bootstrap_option_values.config_override:
        configpaths.append(bootstrap_option_values.config_override)
      if bootstrap_option_values.pantsrc:
        rcfiles = [os.path.expanduser(rcfile) for rcfile in bootstrap_option_values.pantsrc_files]
        existing_rcfiles = filter(os.path.exists, rcfiles)
        configpaths.extend(existing_rcfiles)

      self._post_bootstrap_config = Config.load(configpaths)
      Config.cache(self._post_bootstrap_config)

    return self._bootstrap_options

  def get_full_options(self, known_scopes):
    if not self._full_options:
      # Note: Don't inline this into the Options() call, as this populates
      # self._post_bootstrap_config, which is another argument to that call.
      bootstrap_options = self.get_bootstrap_options()
      self._full_options = Options(self._env,
                                   self._post_bootstrap_config,
                                   known_scopes,
                                   args=self._args,
                                   bootstrap_option_values=bootstrap_options.for_global_scope())

      # The bootstrap options need to be registered on the post-bootstrap Options instance, so it
      # won't choke on them on the command line, and also so we can access their values as regular
      # global-scope options, for convenience.
      register_bootstrap_options(self._full_options.register_global, buildroot=self._buildroot)
    return self._full_options
