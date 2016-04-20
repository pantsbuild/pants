# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import ScopeInfo
from pants.util.contextutil import temporary_dir, temporary_file, temporary_file_path


class BootstrapOptionsTest(unittest.TestCase):

  def _do_test(self, expected_vals, config, env, args):
    self._test_bootstrap_options(config, env, args,
                                 pants_workdir=expected_vals[0],
                                 pants_supportdir=expected_vals[1],
                                 pants_distdir=expected_vals[2])

  def _config_path(self, path):
    if path is None:
      return ["--pants-config-files=[]"]
    else:
      return ["--pants-config-files=['{}']".format(path)]

  def _test_bootstrap_options(self, config, env, args, **expected_entries):
    with temporary_file() as fp:
      fp.write('[DEFAULT]\n')
      if config:
        for k, v in config.items():
          fp.write('{0}: {1}\n'.format(k, v))
      fp.close()

      args = args + self._config_path(fp.name)
      bootstrapper = OptionsBootstrapper(env=env, args=args)
      vals = bootstrapper.get_bootstrap_options().for_global_scope()

      vals_dict = {k: getattr(vals, k) for k in expected_entries}
      self.assertEquals(expected_entries, vals_dict)

  def test_bootstrap_option_values(self):
    # Check all defaults.
    buildroot = get_buildroot()

    def br(path):
      # Returns the full path of the given path under the buildroot.
      return '{}/{}'.format(buildroot, path)

    self._do_test([br('.pants.d'), br('build-support'), br('dist')],
                  config=None, env={}, args=[])

    # Check getting values from config, env and args.
    self._do_test(['/from_config/.pants.d', br('build-support'), br('dist')],
                  config={'pants_workdir': '/from_config/.pants.d'}, env={}, args=[])
    self._do_test([br('.pants.d'), '/from_env/build-support', br('dist')],
                  config=None,
                  env={'PANTS_SUPPORTDIR': '/from_env/build-support'}, args=[])
    self._do_test([br('.pants.d'), br('build-support'), '/from_args/dist'],
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
      args = ['--pants-workdir=/qux'] + self._config_path(fp.name)
      bootstrapper = OptionsBootstrapper(env={
                                           'PANTS_SUPPORTDIR': '/pear'
                                         },
                                         args=args)
      opts = bootstrapper.get_full_options(known_scope_infos=[
        ScopeInfo('', ScopeInfo.GLOBAL),
        ScopeInfo('foo', ScopeInfo.TASK),
        ScopeInfo('fruit', ScopeInfo.TASK)
      ])
      # So we don't choke on these on the cmd line.
      opts.register('', '--pants-workdir')
      opts.register('', '--pants-config-files')

      opts.register('foo', '--bar')
      opts.register('fruit', '--apple')
    self.assertEquals('/qux/baz', opts.for_scope('foo').bar)
    self.assertEquals('/pear/banana', opts.for_scope('fruit').apple)

  def test_create_bootstrapped_multiple_config_override(self):
    # check with multiple config files, the latest values always get taken
    # in this case worker_count will be overwritten, while fruit stays the same
    with temporary_file() as fp:
      fp.write(dedent("""
      [compile.apt]
      worker_count: 1

      [fruit]
      apple: red
      """))
      fp.close()

      args = ['--config-override={}'.format(fp.name)] + self._config_path(fp.name)
      bootstrapper_single_config = OptionsBootstrapper(args=args)

      opts_single_config  = bootstrapper_single_config.get_full_options(known_scope_infos=[
          ScopeInfo('', ScopeInfo.GLOBAL),
          ScopeInfo('compile.apt', ScopeInfo.TASK),
          ScopeInfo('fruit', ScopeInfo.TASK),
      ])
      # So we don't choke on these on the cmd line.
      opts_single_config.register('', '--pants-config-files')
      opts_single_config.register('', '--config-override', type=list)

      opts_single_config.register('compile.apt', '--worker-count')
      opts_single_config.register('fruit', '--apple')

      self.assertEquals('1', opts_single_config.for_scope('compile.apt').worker_count)
      self.assertEquals('red', opts_single_config.for_scope('fruit').apple)

      with temporary_file() as fp2:
        fp2.write(dedent("""
        [compile.apt]
        worker_count: 2
        """))
        fp2.close()

        args = ['--config-override={}'.format(fp.name),
                '--config-override={}'.format(fp2.name)] + self._config_path(fp.name)

        bootstrapper_double_config = OptionsBootstrapper(args=args)

        opts_double_config = bootstrapper_double_config.get_full_options(known_scope_infos=[
          ScopeInfo('', ScopeInfo.GLOBAL),
          ScopeInfo('compile.apt', ScopeInfo.TASK),
          ScopeInfo('fruit', ScopeInfo.TASK),
        ])
        # So we don't choke on these on the cmd line.
        opts_double_config.register('', '--pants-config-files')
        opts_double_config.register('', '--config-override', type=list)
        opts_double_config.register('compile.apt', '--worker-count')
        opts_double_config.register('fruit', '--apple')

        self.assertEquals('2', opts_double_config.for_scope('compile.apt').worker_count)
        self.assertEquals('red', opts_double_config.for_scope('fruit').apple)

  def test_full_options_caching(self):
    with temporary_file_path() as config:
      args = self._config_path(config)
      bootstrapper = OptionsBootstrapper(env={}, args=args)

      opts1 = bootstrapper.get_full_options(known_scope_infos=[ScopeInfo('', ScopeInfo.GLOBAL),
                                                               ScopeInfo('foo', ScopeInfo.TASK)])
      opts2 = bootstrapper.get_full_options(known_scope_infos=[ScopeInfo('foo', ScopeInfo.TASK),
                                                               ScopeInfo('', ScopeInfo.GLOBAL)])
      self.assertIs(opts1, opts2)

      opts3 = bootstrapper.get_full_options(known_scope_infos=[ScopeInfo('', ScopeInfo.GLOBAL),
                                                               ScopeInfo('foo', ScopeInfo.TASK),
                                                               ScopeInfo('', ScopeInfo.GLOBAL)])
      self.assertIs(opts1, opts3)

      opts4 = bootstrapper.get_full_options(known_scope_infos=[ScopeInfo('', ScopeInfo.GLOBAL)])
      self.assertIsNot(opts1, opts4)

      opts5 = bootstrapper.get_full_options(known_scope_infos=[ScopeInfo('', ScopeInfo.GLOBAL)])
      self.assertIs(opts4, opts5)
      self.assertIsNot(opts1, opts5)

  def test_bootstrap_short_options(self):
    def parse_options(*args):
      full_args = list(args) + self._config_path(None)
      return OptionsBootstrapper(args=full_args).get_bootstrap_options().for_global_scope()

    # No short options passed - defaults presented.
    vals = parse_options()
    self.assertIsNone(vals.logdir)
    self.assertEqual('info', vals.level)

    # Unrecognized short options passed and ignored - defaults presented.
    vals = parse_options('-_UnderscoreValue', '-^')
    self.assertIsNone(vals.logdir)
    self.assertEqual('info', vals.level)

    vals = parse_options('-d/tmp/logs', '-ldebug')
    self.assertEqual('/tmp/logs', vals.logdir)
    self.assertEqual('debug', vals.level)

  def test_bootstrap_options_passthrough_dup_ignored(self):
    def parse_options(*args):
      full_args = list(args) + self._config_path(None)
      return OptionsBootstrapper(args=full_args).get_bootstrap_options().for_global_scope()

    vals = parse_options('main', 'args', '-d/tmp/frogs', '--', '-d/tmp/logs')
    self.assertEqual('/tmp/frogs', vals.logdir)

    vals = parse_options('main', 'args', '--', '-d/tmp/logs')
    self.assertIsNone(vals.logdir)

  def test_bootstrap_options_explicit_config_path(self):
    def config_path(*args, **env):
      return OptionsBootstrapper.get_config_file_paths(env, args)

    self.assertEqual(['/foo/bar/pants.ini'],
                     config_path('main', 'args', "--pants-config-files=['/foo/bar/pants.ini']"))

    self.assertEqual(['/from/env1', '/from/env2'],
                     config_path('main', 'args',
                                 PANTS_CONFIG_FILES="['/from/env1', '/from/env2']"))

    self.assertEqual(['/from/flag'],
                     config_path('main', 'args', '-x', "--pants-config-files=['/from/flag']",
                                 'goal', '--other-flag', PANTS_CONFIG_FILES="['/from/env']"))

    # Test appending to the default.
    self.assertEqual(['{}/pants.ini'.format(get_buildroot()), '/from/env', '/from/flag'],
                     config_path('main', 'args', '-x', "--pants-config-files=+['/from/flag']",
                                 'goal', '--other-flag', PANTS_CONFIG_FILES="+['/from/env']"))

    # Test replacing the default, then appending.
    self.assertEqual(['/from/env', '/from/flag'],
                     config_path('main', 'args', '-x', "--pants-config-files=+['/from/flag']",
                                 'goal', '--other-flag', PANTS_CONFIG_FILES="['/from/env']"))

    self.assertEqual(['/from/flag'],
                     config_path('main', 'args', '-x', "--pants-config-files=['/from/flag']",
                                 'goal', '--other-flag', PANTS_CONFIG_FILES="+['/from/env']"))

  def test_setting_pants_config_in_config(self):
    # Test that setting pants_config in the config file has no effect.
    with temporary_dir() as tmpdir:
      config1 = os.path.join(tmpdir, 'config1')
      config2 = os.path.join(tmpdir, 'config2')
      with open(config1, 'w') as out1:
        out1.write(b"[DEFAULT]\npants_config_files: ['{}']\nlogdir: logdir1\n".format(config2))
      with open(config2, 'w') as out2:
        out2.write(b'[DEFAULT]\nlogdir: logdir2\n')

      ob = OptionsBootstrapper(env={}, args=["--pants-config-files=['{}']".format(config1)])
      logdir = ob.get_bootstrap_options().for_global_scope().logdir
      self.assertEqual('logdir1', logdir)
