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
  """Register options whose values can be interpolated into the config file.

  The values of these options are determined before those of any other options, so that
  they can be used to compute the values of the other options.
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
  option_names = []

  def capture_option_names(*args, **kwargs):
    flags.update(args)
    arg = next((a for a in args if a.startswith('--')), args[0])
    option_names.append(arg.lstrip('-').replace('-', '_'))

  register_bootstrap_options(capture_option_names, buildroot=buildroot)
  bargs = filter(lambda x: x.partition('=')[0] in flags, args)

  bootstrap_options = Options(env=env, config=config, known_scopes=[GLOBAL_SCOPE], args=bargs)
  register_bootstrap_options(bootstrap_options.register_global, buildroot=buildroot)
  vals = bootstrap_options.for_global_scope()

  return {k: getattr(vals, k) for k in option_names }


def create_bootstrapped_options(known_scopes, env=None, configpath=None, args=None, buildroot=None):
  """Create an Options instance with appropriate bootstrapping."""
  env = env or os.environ.copy()
  pre_bootstrap_config = Config.load(configpath)
  args = args or sys.argv
  buildroot = buildroot or get_buildroot()
  bootstrap_option_values = get_bootstrap_option_values(env, pre_bootstrap_config, args, buildroot)
  Config._defaults.update(bootstrap_option_values)

  # Ensure that we cache the post-bootstrap version.
  Config.clear_cache()
  post_bootstrap_config = Config.from_cache(configpath)

  opts = Options(env, post_bootstrap_config, known_scopes, args=args)

  # The bootstrap options need to be registered on the Options instance, so it won't choke on
  # them if specified on the command line, and also so we can access them in code if needed.
  register_bootstrap_options(opts.register_global, buildroot=buildroot)
  return opts
