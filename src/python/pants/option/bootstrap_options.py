# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import sys

from pants.base.config import Config
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.base.build_environment import get_buildroot
from pants.option.options import Options


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
  register('--pants-workdir', metavar='<dir>', default=os.path.join(buildroot, '.pants.d'),
           help='Write intermediate output files to this dir.')
  register('--pants-supportdir', metavar='<dir>', default=os.path.join(buildroot, 'build-support'),
           help='Use support files from this dir.')
  register('--pants-distdir', metavar='<dir>', default=os.path.join(buildroot, 'dist'),
           help='Write end-product artifacts to this dir.')


def get_bootstrap_option_values(env=None, config=None, args=None, buildroot=None):
  """Get the values of just the bootstrap options."""
  # Filter just the bootstrap args, so we don't choke on other global-scope args on the cmd line.
  flags = set()
  def capture_the_flags(*args, **kwargs):
    flags.update(args)
  register_bootstrap_options(capture_the_flags, buildroot=buildroot)
  bargs = filter(lambda x: x.partition('=')[0] in flags, args or [])

  bootstrap_options = Options(env=env, config=config, known_scopes=[GLOBAL_SCOPE], args=bargs)
  register_bootstrap_options(bootstrap_options.register_global, buildroot=buildroot)
  return bootstrap_options.for_global_scope()


def create_bootstrapped_options(known_scopes, env=None, configpath=None, args=None, buildroot=None):
  """Create an Options instance with appropriate bootstrapping."""
  env = env or os.environ.copy()
  pre_bootstrap_config = Config.load(configpath)
  args = args or sys.argv
  buildroot = buildroot or get_buildroot()
  bootstrap_option_values = get_bootstrap_option_values(env, pre_bootstrap_config, args, buildroot)
  Config.reset_default_bootstrap_option_values(bootstrap_option_values)

  # Ensure that we cache the post-bootstrap version.
  Config.clear_cache()
  post_bootstrap_config = Config.from_cache(configpath)

  opts = Options(env, post_bootstrap_config, known_scopes, args=args,
                 bootstrap_option_values=bootstrap_option_values)

  # The bootstrap options need to be registered on the post-bootstrap Options instance, so it won't
  # choke on them if specified on the command line, and also so we can access their values as
  # regular global-scope options, if needed.
  register_bootstrap_options(opts.register_global, buildroot=buildroot)
  return opts
