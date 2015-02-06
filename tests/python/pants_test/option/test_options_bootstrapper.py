# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from textwrap import dedent

from pants.base.config import Config
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.contextutil import temporary_file


class BootstrapOptionsTest(unittest.TestCase):
  def tearDown(self):
    Config.reset_default_bootstrap_option_values()

  def _do_test(self, expected_vals, config, env, args):
    self._test_bootstrap_options(config, env, args,
                                 pants_workdir=expected_vals[0],
                                 pants_supportdir=expected_vals[1],
                                 pants_distdir=expected_vals[2])

  def _test_bootstrap_options(self, config, env, args, **expected_entries):
    with temporary_file() as fp:
      fp.write('[DEFAULT]\n')
      if config:
        for k, v in config.items():
          fp.write('{0}: {1}\n'.format(k, v))
      fp.close()

      vals = OptionsBootstrapper(env=env, configpath=fp.name, args=args,
                                 buildroot='/buildroot').get_bootstrap_options().for_global_scope()

      vals_dict = {k: getattr(vals, k) for k in expected_entries}
      self.assertEquals(expected_entries, vals_dict)

  def test_bootstrap_option_values(self):
    # Check all defaults.
    self._do_test(['/buildroot/.pants.d', '/buildroot/build-support', '/buildroot/dist'],
                  config=None, env={}, args=[])

    # Check getting values from config, env and args.
    self._do_test(['/from_config/.pants.d', '/buildroot/build-support', '/buildroot/dist'],
                  config={'pants_workdir': '/from_config/.pants.d'}, env={}, args=[])
    self._do_test(['/buildroot/.pants.d', '/from_env/build-support', '/buildroot/dist'],
                  config=None,
                  env={'PANTS_SUPPORTDIR': '/from_env/build-support'}, args=[])
    self._do_test(['/buildroot/.pants.d', '/buildroot/build-support', '/from_args/dist'],
                  config={}, env={}, args=['--pants-distdir=/from_args/dist'])

    # Check that args > env > config.
    self._do_test(['/from_config/.pants.d', '/from_env/build-support', '/from_args/dist'],
                  config={
                    'pants_workdir': '/from_config/.pants.d',
                    'pants_supportdir': '/from_config/build-support',
                    'pants_distdir': '/from_config/dist'
                  },
                  env={
                    'PANTS_SUPPORTDIR': '/from_env/build-support',
                    'PANTS_DISTDIR': '/from_env/dist'
                  },
                  args=['--pants-distdir=/from_args/dist'])

    # Check that unrelated args and config don't confuse us.
    self._do_test(['/from_config/.pants.d', '/from_env/build-support', '/from_args/dist'],
                  config={
                    'pants_workdir': '/from_config/.pants.d',
                    'pants_supportdir': '/from_config/build-support',
                    'pants_distdir': '/from_config/dist',
                    'unrelated': 'foo'
                  },
                  env={
                    'PANTS_SUPPORTDIR': '/from_env/build-support',
                    'PANTS_DISTDIR': '/from_env/dist'
                  },
                  args=['--pants-distdir=/from_args/dist', '--foo=bar', '--baz'])

  def test_bootstrap_bool_option_values(self):
    # Check the default.
    self._test_bootstrap_options(config=None, env={}, args=[], pantsrc=True)

    # Check an override via flag - currently bools (for store_true and store_false actions) cannot
    # be inverted from the default via env vars or the config.
    self._test_bootstrap_options(config={}, env={}, args=['--no-pantsrc'], pantsrc=False)

    self._test_bootstrap_options(config={'pantsrc': False}, env={}, args=[], pantsrc=False)

    self._test_bootstrap_options(config={}, env={'PANTS_PANTSRC': 'False'}, args=[], pantsrc=False)


  def test_create_bootstrapped_options(self):
    # Check that we can set a bootstrap option from a cmd-line flag and have that interpolate
    # correctly into regular config.
    with temporary_file() as fp:
      fp.write(dedent("""
      [foo]
      bar: %(pants_workdir)s/baz

      [fruit]
      apple: %(pants_supportdir)s/banana
      """))
      fp.close()
      bootstrapper = OptionsBootstrapper(env={
                                           'PANTS_SUPPORTDIR': '/pear'
                                         },
                                         configpath=fp.name,
                                         args=['--pants-workdir=/qux'])
      opts = bootstrapper.get_full_options(known_scopes=['', 'foo', 'fruit'])
      opts.register('foo', '--bar')
      opts.register('fruit', '--apple')
    self.assertEquals('/qux/baz', opts.for_scope('foo').bar)
    self.assertEquals('/pear/banana', opts.for_scope('fruit').apple)
