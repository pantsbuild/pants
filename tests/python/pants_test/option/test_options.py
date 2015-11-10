# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shlex
import tempfile
import unittest
import warnings
from contextlib import contextmanager
from textwrap import dedent

from pants.base.deprecated import PastRemovalVersionError
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.config import Config
from pants.option.custom_types import dict_option, file_option, list_option, target_list_option
from pants.option.errors import (BooleanOptionImplicitVal, BooleanOptionNameWithNo,
                                 BooleanOptionType, FrozenRegistration, ImplicitValIsNone,
                                 InvalidAction, InvalidKwarg, NoOptionNames, OptionNameDash,
                                 OptionNameDoubleDash, ParseError, RecursiveSubsystemOption,
                                 Shadowing)
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.option_tracker import OptionTracker
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.parser import Parser
from pants.option.ranked_value import RankedValue
from pants.option.scope import ScopeInfo
from pants.util.contextutil import temporary_file, temporary_file_path
from pants.util.dirutil import safe_mkdtemp


def task(scope):
  return ScopeInfo(scope, ScopeInfo.TASK)


def intermediate(scope):
  return ScopeInfo(scope, ScopeInfo.INTERMEDIATE)


def subsystem(scope):
  return ScopeInfo(scope, ScopeInfo.SUBSYSTEM)


class OptionsTest(unittest.TestCase):
  _known_scope_infos = [intermediate('compile'),
                        task('compile.java'),
                        task('compile.scala'),
                        intermediate('stale'),
                        intermediate('test'),
                        task('test.junit'),
                        task('simple'),
                        task('simple-dashed'),
                        task('scoped.a.bit'),
                        task('scoped.and-dashed'),
                        task('fromfile')]

  def _register(self, options):
    def register_global(*args, **kwargs):
      options.register(GLOBAL_SCOPE, *args, **kwargs)

    register_global('-z', '--verbose', action='store_true', help='Verbose output.', recursive=True)
    register_global('-n', '--num', type=int, default=99, recursive=True, fingerprint=True)
    register_global('--y', action='append', type=int)
    register_global('--config-override', action='append')

    register_global('--pants-foo')
    register_global('--bar-baz')
    register_global('--store-true-flag', action='store_true', fingerprint=True)
    register_global('--store-false-flag', action='store_false')
    register_global('--store-true-def-true-flag', action='store_true', default=True)
    register_global('--store-true-def-false-flag', action='store_true', default=False)
    register_global('--store-false-def-false-flag', action='store_false', default=False)
    register_global('--store-false-def-true-flag', action='store_false', default=True)

    # Choices.
    register_global('--str-choices', choices=['foo', 'bar'])
    register_global('--int-choices', choices=[42, 99], type=int, action='append')

    # Custom types.
    register_global('--dicty', type=dict_option, default='{"a": "b"}')
    register_global('--listy', type=list_option, default='[1, 2, 3]')
    register_global('--target_listy', type=target_list_option, default=[':a', ':b'])
    register_global('--filey', type=file_option, default='default.txt')

    # Implicit value.
    register_global('--implicit-valuey', default='default', implicit_value='implicit')

    # For the design doc example test.
    register_global('--a', type=int, recursive=True)
    register_global('--b', type=int, recursive=True)

    # Deprecated global options
    register_global('--global-crufty', deprecated_version='999.99.9',
                    deprecated_hint='use a less crufty global option')
    register_global('--global-crufty-boolean', action='store_true', deprecated_version='999.99.9',
                    deprecated_hint='say no to crufty global options')

    # For the design doc example test.
    options.register('compile', '--c', type=int, recursive=True)

    # Test deprecated options with a scope
    options.register('stale', '--still-good')
    options.register('stale', '--crufty',
                     deprecated_version='999.99.9',
                     deprecated_hint='use a less crufty stale scoped option')
    options.register('stale', '--crufty-boolean', action='store_true',
                     deprecated_version='999.99.9',
                     deprecated_hint='say no to crufty, stale scoped options')

    # For task identity test
    options.register('compile.scala', '--modifycompile', fingerprint=True)
    options.register('compile.scala', '--modifylogs')

    # For scoped env vars test
    options.register('simple', '--spam')
    options.register('simple-dashed', '--spam')
    options.register('scoped.a.bit', '--spam')
    options.register('scoped.and-dashed', '--spam')

    # For fromfile test
    options.register('fromfile', '--string', fromfile=True)
    options.register('fromfile', '--intvalue', type=int, fromfile=True)
    options.register('fromfile', '--dictvalue', type=dict_option, fromfile=True)
    options.register('fromfile', '--listvalue', type=list_option, fromfile=True)
    options.register('fromfile', '--appendvalue', action='append', type=int, fromfile=True)

  def _create_config(self, config):
    with open(os.path.join(safe_mkdtemp(), 'test_config.ini'), 'w') as fp:
      for section, options in config.items():
        fp.write('[{}]\n'.format(section))
        for key, value in options.items():
          fp.write('{}: {}\n'.format(key, value))
    return Config.load(configpaths=[fp.name])

  def _parse(self, args_str, env=None, config=None, bootstrap_option_values=None):
    args = shlex.split(str(args_str))
    options = Options.create(env=env or {},
                             config=self._create_config(config or {}),
                             known_scope_infos=OptionsTest._known_scope_infos,
                             args=args,
                             bootstrap_option_values=bootstrap_option_values,
                             option_tracker=OptionTracker())
    self._register(options)
    return options

  def _parse_type_int(self, args_str, env=None, config=None, bootstrap_option_values=None,
                      action='store'):
    args = shlex.split(str(args_str))
    options = Options.create(env=env or {},
                             config=self._create_config(config or {}),
                             known_scope_infos=OptionsTest._known_scope_infos,
                             args=args,
                             bootstrap_option_values=bootstrap_option_values,
                             option_tracker=OptionTracker())
    options.register(GLOBAL_SCOPE, '--config-override', action=action, type=int)
    return options

  def test_env_type_int(self):
    options = self._parse_type_int('./pants ',
                                   action='append',
                                   env={'PANTS_CONFIG_OVERRIDE': "['123','456']"})
    self.assertEqual([123, 456], options.for_global_scope().config_override)

    options = self._parse_type_int('./pants ', env={'PANTS_CONFIG_OVERRIDE': "123"})
    self.assertEqual(123, options.for_global_scope().config_override)

  def test_env_bad_override_var(self):
    """Check for bad PANTS_CONFIG_OVERRIDE values.

    Checks for a case where an environment variable exists like:

        PANTS_CONFIG_OVERRIDE=old_style_pants.ini

    Which was known to throw an unhandled NameError for 'old_style_pants' during the eval().
    """
    with self.assertRaisesRegexp(ParseError, 'config.*override'):
      options = self._parse('./pants ', env={'PANTS_CONFIG_OVERRIDE': 'old_style_pants.ini'})
      options.for_global_scope().config_override

  def test_arg_scoping(self):
    # Some basic smoke tests.
    options = self._parse('./pants --verbose')
    self.assertEqual(True, options.for_global_scope().verbose)
    options = self._parse('./pants -z compile path/to/tgt')
    self.assertEqual(['path/to/tgt'], options.target_specs)
    self.assertEqual(True, options.for_global_scope().verbose)

    with self.assertRaises(ParseError):
      self._parse('./pants --unregistered-option compile').for_global_scope()

    # Scoping of different values of the same option.
    # Also tests the --no-* boolean flag inverses.
    options = self._parse('./pants --verbose compile.java --no-verbose')
    self.assertEqual(True, options.for_global_scope().verbose)
    self.assertEqual(True, options.for_scope('compile').verbose)
    self.assertEqual(False, options.for_scope('compile.java').verbose)

    options = self._parse('./pants --verbose compile --no-verbose compile.java -z test '
                          'test.junit --no-verbose')
    self.assertEqual(True, options.for_global_scope().verbose)
    self.assertEqual(False, options.for_scope('compile').verbose)
    self.assertEqual(True, options.for_scope('compile.java').verbose)
    self.assertEqual(True, options.for_scope('test').verbose)
    self.assertEqual(False, options.for_scope('test.junit').verbose)

    # Test action=append option.
    options = self._parse('./pants', config={'DEFAULT': {'y': ['88', '-99']}})
    self.assertEqual([88, -99], options.for_global_scope().y)

    options = self._parse('./pants --y=5 --y=-6 --y=77',
                          config={'DEFAULT': {'y': ['88', '-99']}})
    self.assertEqual([88, -99, 5, -6, 77], options.for_global_scope().y)

    options = self._parse('./pants')
    self.assertEqual([], options.for_global_scope().y)

    options = self._parse('./pants ', env={'PANTS_CONFIG_OVERRIDE': "['123','456']"})
    self.assertEqual(['123','456'], options.for_global_scope().config_override)

    options = self._parse('./pants ', env={'PANTS_CONFIG_OVERRIDE': "['']"})
    self.assertEqual([''], options.for_global_scope().config_override)

    # Test list-typed option.
    options = self._parse('./pants --listy=\'["c", "d"]\'',
                          config={'DEFAULT': {'listy': '["a", "b"]'}})
    self.assertEqual(['c', 'd'], options.for_global_scope().listy)

    # Test dict-typed option.
    options = self._parse('./pants --dicty=\'{"c": "d"}\'')
    self.assertEqual({'c': 'd'}, options.for_global_scope().dicty)

    # Test target_list-typed option.
    options = self._parse('./pants --target_listy=\'["//:foo", "//:bar"]\'')
    self.assertEqual(['//:foo', '//:bar'], options.for_global_scope().target_listy)

    # Test file-typed option.
    with temporary_file_path() as fp:
      options = self._parse('./pants --filey="{}"'.format(fp))
      self.assertEqual(fp, options.for_global_scope().filey)

  def test_boolean_defaults(self):
    options = self._parse('./pants')
    self.assertFalse(options.for_global_scope().store_true_flag)
    self.assertFalse(options.for_global_scope().store_false_flag)
    self.assertFalse(options.for_global_scope().store_true_def_false_flag)
    self.assertTrue(options.for_global_scope().store_true_def_true_flag)
    self.assertFalse(options.for_global_scope().store_false_def_false_flag)
    self.assertTrue(options.for_global_scope().store_false_def_true_flag)

  def test_boolean_set_option(self):
    options = self._parse('./pants --store-true-flag --store-false-flag '
                          ' --store-true-def-true-flag --store-true-def-false-flag '
                          ' --store-false-def-true-flag --store-false-def-false-flag')

    self.assertTrue(options.for_global_scope().store_true_flag)
    self.assertFalse(options.for_global_scope().store_false_flag)
    self.assertTrue(options.for_global_scope().store_true_def_false_flag)
    self.assertTrue(options.for_global_scope().store_true_def_true_flag)
    self.assertFalse(options.for_global_scope().store_false_def_false_flag)
    self.assertFalse(options.for_global_scope().store_false_def_true_flag)

  def test_boolean_negate_option(self):
    options = self._parse('./pants --no-store-true-flag --no-store-false-flag '
                          ' --no-store-true-def-true-flag --no-store-true-def-false-flag '
                          ' --no-store-false-def-true-flag --no-store-false-def-false-flag')
    self.assertFalse(options.for_global_scope().store_true_flag)
    self.assertTrue(options.for_global_scope().store_false_flag)
    self.assertFalse(options.for_global_scope().store_true_def_false_flag)
    self.assertFalse(options.for_global_scope().store_true_def_true_flag)
    self.assertTrue(options.for_global_scope().store_false_def_false_flag)
    self.assertTrue(options.for_global_scope().store_false_def_true_flag)

  def test_boolean_config_override_true(self):
    options = self._parse('./pants', config={'DEFAULT': {'store_true_flag': True,
                                                         'store_false_flag': True,
                                                         'store_true_def_true_flag': True,
                                                         'store_true_def_false_flag': True,
                                                         'store_false_def_true_flag': True,
                                                         'store_false_def_false_flag': True,
                                                         }})
    self.assertTrue(options.for_global_scope().store_true_flag)
    self.assertTrue(options.for_global_scope().store_false_flag)
    self.assertTrue(options.for_global_scope().store_true_def_false_flag)
    self.assertTrue(options.for_global_scope().store_true_def_true_flag)
    self.assertTrue(options.for_global_scope().store_false_def_false_flag)
    self.assertTrue(options.for_global_scope().store_false_def_true_flag)

  def test_boolean_config_override_false(self):
    options = self._parse('./pants', config={'DEFAULT': {'store_true_flag': False,
                                                         'store_false_flag': False,
                                                         'store_true_def_true_flag': False,
                                                         'store_true_def_false_flag': False,
                                                         'store_false_def_true_flag': False,
                                                         'store_false_def_false_flag': False,
                                                         }})
    self.assertFalse(options.for_global_scope().store_true_flag)
    self.assertFalse(options.for_global_scope().store_false_flag)
    self.assertFalse(options.for_global_scope().store_true_def_false_flag)
    self.assertFalse(options.for_global_scope().store_true_def_true_flag)
    self.assertFalse(options.for_global_scope().store_false_def_false_flag)
    self.assertFalse(options.for_global_scope().store_false_def_true_flag)

  def test_boolean_invalid_value(self):
    with self.assertRaises(Parser.BooleanConversionError):
      self._parse('./pants', config={'DEFAULT': {'store_true_flag': 11,
                                                 }}).for_global_scope()
    with self.assertRaises(Parser.BooleanConversionError):
      self._parse('./pants', config={'DEFAULT': {'store_true_flag': 'AlmostTrue',
                                               }}).for_global_scope()

  def test_defaults(self):
    # Hard-coded defaults.
    options = self._parse('./pants compile.java -n33')
    self.assertEqual(99, options.for_global_scope().num)
    self.assertEqual(99, options.for_scope('compile').num)
    self.assertEqual(33, options.for_scope('compile.java').num)
    self.assertEqual(99, options.for_scope('test').num)
    self.assertEqual(99, options.for_scope('test.junit').num)

    options = self._parse('./pants compile -n22 compile.java -n33')
    self.assertEqual(99, options.for_global_scope().num)
    self.assertEqual(22, options.for_scope('compile').num)
    self.assertEqual(33, options.for_scope('compile.java').num)

    # Get defaults from config and environment.
    config = {
      'DEFAULT': {'num': '88'},
      'compile': {'num': '77'},
      'compile.java': {'num': '66'}
    }
    options = self._parse('./pants compile.java -n22', config=config)
    self.assertEqual(88, options.for_global_scope().num)
    self.assertEqual(77, options.for_scope('compile').num)
    self.assertEqual(22, options.for_scope('compile.java').num)

    env = {
      'PANTS_COMPILE_NUM': '55'
    }
    options = self._parse('./pants compile', env=env, config=config)
    self.assertEqual(88, options.for_global_scope().num)
    self.assertEqual(55, options.for_scope('compile').num)
    self.assertEqual(55, options.for_scope('compile.java').num)

    options = self._parse('./pants compile.java -n44', env=env, config=config)
    self.assertEqual(88, options.for_global_scope().num)
    self.assertEqual(55, options.for_scope('compile').num)
    self.assertEqual(44, options.for_scope('compile.java').num)

  def test_choices(self):
    options = self._parse('./pants --str-choices=foo')
    self.assertEqual('foo', options.for_global_scope().str_choices)
    options = self._parse('./pants', config={'DEFAULT': {'str_choices': 'bar'}})
    self.assertEqual('bar', options.for_global_scope().str_choices)
    with self.assertRaises(ParseError):
      options = self._parse('./pants --str-choices=baz')
      options.for_global_scope()
    with self.assertRaises(ParseError):
      options = self._parse('./pants', config={'DEFAULT': {'str_choices': 'baz'}})
      options.for_global_scope()

    options = self._parse('./pants --int-choices=42 --int-choices=99')
    self.assertEqual([42, 99], options.for_global_scope().int_choices)

  def test_validation(self):
    def assertError(expected_error, *args, **kwargs):
      with self.assertRaises(expected_error):
        options = Options.create(args=[], env={}, config=self._create_config({}),
                                 known_scope_infos=[], option_tracker=OptionTracker())
        options.register(GLOBAL_SCOPE, *args, **kwargs)
        options.for_global_scope()

    assertError(NoOptionNames)
    assertError(OptionNameDash, 'badname')
    assertError(OptionNameDoubleDash, '-badname')
    assertError(InvalidAction, '--foo', action='store_const')
    assertError(InvalidKwarg, '--foo', badkwarg=42)
    assertError(ImplicitValIsNone, '--foo', implicit_value=None)
    assertError(BooleanOptionType, '--foo', action='store_true', type=int)
    assertError(BooleanOptionImplicitVal, '--foo', action='store_true', implicit_value=False)
    assertError(BooleanOptionNameWithNo, '--no-foo', action='store_true')

  def test_frozen_registration(self):
    options = Options.create(args=[], env={}, config=self._create_config({}),
                             known_scope_infos=[task('foo')], option_tracker=OptionTracker())
    options.register('foo', '--arg1')
    with self.assertRaises(FrozenRegistration):
      options.register(GLOBAL_SCOPE, '--arg2')

  def test_implicit_value(self):
    options = self._parse('./pants')
    self.assertEqual('default', options.for_global_scope().implicit_valuey)
    options = self._parse('./pants --implicit-valuey')
    self.assertEqual('implicit', options.for_global_scope().implicit_valuey)
    options = self._parse('./pants --implicit-valuey=explicit')
    self.assertEqual('explicit', options.for_global_scope().implicit_valuey)

  def test_shadowing(self):
    options = Options.create(env={},
                             config=self._create_config({}),
                             known_scope_infos=[task('bar'), intermediate('foo'), task('foo.bar')],
                             args='./pants',
                             option_tracker=OptionTracker())
    options.register('', '--opt1')
    options.register('foo', '-o', '--opt2')
    with self.assertRaises(Shadowing):
      options.register('bar', '--opt1')
    with self.assertRaises(Shadowing):
      options.register('foo.bar', '--opt1')
    with self.assertRaises(Shadowing):
      options.register('foo.bar', '--opt2')
    with self.assertRaises(Shadowing):
      options.register('foo.bar', '--opt1', '--opt3')
    with self.assertRaises(Shadowing):
      options.register('foo.bar', '--opt3', '--opt2')

  def test_recursion(self):
    # Recursive option.
    options = self._parse('./pants -n=5 compile -n=6')
    self.assertEqual(5, options.for_global_scope().num)
    self.assertEqual(6, options.for_scope('compile').num)

    # Non-recursive option.
    options = self._parse('./pants --bar-baz=foo')
    self.assertEqual('foo', options.for_global_scope().bar_baz)
    options = self._parse('./pants compile --bar-baz=foo')
    with self.assertRaises(ParseError):
      options.for_scope('compile')

  def test_no_recursive_subsystem_options(self):
    options = Options.create(env={},
                             config=self._create_config({}),
                             known_scope_infos=[subsystem('foo')],
                             args='./pants',
                             option_tracker=OptionTracker())
    # All subsystem options are implicitly recursive (a subscope of subsystem scope represents
    # a separate instance of the subsystem, so it needs all the options).
    # We disallow explicit specification of recursive (even if set to True), to avoid confusion.
    with self.assertRaises(RecursiveSubsystemOption):
      options.register('foo', '--bar', recursive=False)
      options.for_scope('foo')
    with self.assertRaises(RecursiveSubsystemOption):
      options.register('foo', '--baz', recursive=True)
      options.for_scope('foo')

  def test_is_known_scope(self):
    options = self._parse('./pants')
    for scope_info in self._known_scope_infos:
      self.assertTrue(options.is_known_scope(scope_info.scope))
    self.assertFalse(options.is_known_scope('nonexistent_scope'))

  def test_designdoc_example(self):
    # The example from the design doc.
    # Get defaults from config and environment.
    config = {
      'DEFAULT': {'b': '99'},
      'compile': {'a': '88', 'c': '77'},
    }

    env = {
      'PANTS_COMPILE_C': '66'
    }

    options = self._parse('./pants --a=1 compile --b=2 compile.java --a=3 --c=4',
                          env=env, config=config)

    self.assertEqual(1, options.for_global_scope().a)
    self.assertEqual(99, options.for_global_scope().b)
    with self.assertRaises(AttributeError):
      _ = options.for_global_scope().c

    self.assertEqual(1, options.for_scope('compile').a)
    self.assertEqual(2, options.for_scope('compile').b)
    self.assertEqual(66, options.for_scope('compile').c)

    self.assertEqual(3, options.for_scope('compile.java').a)
    self.assertEqual(2, options.for_scope('compile.java').b)
    self.assertEqual(4, options.for_scope('compile.java').c)

  def test_file_spec_args(self):
    with tempfile.NamedTemporaryFile() as tmp:
      tmp.write(dedent(
        '''
        foo
        bar
        '''
      ))
      tmp.flush()
      cmdline = './pants --target-spec-file={filename} compile morx:tgt fleem:tgt'.format(
        filename=tmp.name)
      bootstrapper = OptionsBootstrapper(args=shlex.split(cmdline))
      bootstrap_options = bootstrapper.get_bootstrap_options().for_global_scope()
      options = self._parse(cmdline, bootstrap_option_values=bootstrap_options)
      sorted_specs = sorted(options.target_specs)
      self.assertEqual(['bar', 'fleem:tgt', 'foo', 'morx:tgt'], sorted_specs)

  def test_passthru_args(self):
    options = self._parse('./pants compile foo -- bar --baz')
    self.assertEqual(['bar', '--baz'], options.passthru_args_for_scope('compile'))
    self.assertEqual(['bar', '--baz'], options.passthru_args_for_scope('compile.java'))
    self.assertEqual(['bar', '--baz'], options.passthru_args_for_scope('compile.scala'))
    self.assertEqual([], options.passthru_args_for_scope('test'))
    self.assertEqual([], options.passthru_args_for_scope(''))
    self.assertEqual([], options.passthru_args_for_scope(None))

  def test_global_scope_env_vars(self):
    def check_pants_foo(expected_val, env):
      val = self._parse('./pants', env=env).for_global_scope().pants_foo
      self.assertEqual(expected_val, val)

    check_pants_foo('AAA', {
      'PANTS_DEFAULT_PANTS_FOO': 'AAA',
      'PANTS_PANTS_FOO': 'BBB',
      'PANTS_FOO': 'CCC',
    })
    check_pants_foo('BBB', {
      'PANTS_PANTS_FOO': 'BBB',
      'PANTS_FOO': 'CCC',
    })
    check_pants_foo('CCC', {
      'PANTS_FOO': 'CCC',
    })
    check_pants_foo(None, {
    })
    # Check that an empty string is distinct from no value being specified.
    check_pants_foo('', {
      'PANTS_PANTS_FOO': '',
      'PANTS_FOO': 'CCC',
    })

    # A global option that doesn't begin with 'pants-': Setting BAR_BAZ should have no effect.

    def check_bar_baz(expected_val, env):
      val = self._parse('./pants', env=env).for_global_scope().bar_baz
      self.assertEqual(expected_val, val)

    check_bar_baz('AAA', {
      'PANTS_DEFAULT_BAR_BAZ': 'AAA',
      'PANTS_BAR_BAZ': 'BBB',
      'BAR_BAZ': 'CCC',
    })
    check_bar_baz('BBB', {
      'PANTS_BAR_BAZ': 'BBB',
      'BAR_BAZ': 'CCC',
    })
    check_bar_baz(None, {
      'BAR_BAZ': 'CCC',
    })
    check_bar_baz(None, {
    })

  def test_scoped_env_vars(self):
    def check_scoped_spam(scope, expected_val, env):
      val = self._parse('./pants', env=env).for_scope(scope).spam
      self.assertEqual(expected_val, val)

    check_scoped_spam('simple', 'value', {'PANTS_SIMPLE_SPAM': 'value'})
    check_scoped_spam('simple-dashed', 'value', {'PANTS_SIMPLE_DASHED_SPAM': 'value'})
    check_scoped_spam('scoped.a.bit', 'value', {'PANTS_SCOPED_A_BIT_SPAM': 'value'})
    check_scoped_spam('scoped.and-dashed', 'value', {'PANTS_SCOPED_AND_DASHED_SPAM': 'value'})

  def test_drop_flag_values(self):
    options = self._parse('./pants --bar-baz=fred -n33 --pants-foo=red simple -n1',
                          env={'PANTS_FOO': 'BAR'},
                          config={'simple': {'num': 42}})
    defaulted_only_options = options.drop_flag_values()

    # No option value supplied in any form.
    self.assertEqual('fred', options.for_global_scope().bar_baz)
    self.assertIsNone(defaulted_only_options.for_global_scope().bar_baz)

    # A defaulted option value.
    self.assertEqual(33, options.for_global_scope().num)
    self.assertEqual(99, defaulted_only_options.for_global_scope().num)

    # A config specified option value.
    self.assertEqual(1, options.for_scope('simple').num)
    self.assertEqual(42, defaulted_only_options.for_scope('simple').num)

    # An env var specified option value.
    self.assertEqual('red', options.for_global_scope().pants_foo)
    self.assertEqual('BAR', defaulted_only_options.for_global_scope().pants_foo)

  def test_deprecated_option_past_removal(self):
    with self.assertRaises(PastRemovalVersionError):
      options = Options.create(env={},
                               config=self._create_config({}),
                               known_scope_infos=OptionsTest._known_scope_infos,
                               args='./pants',
                               option_tracker=OptionTracker())
      options.register(GLOBAL_SCOPE, '--too-old-option', deprecated_version='0.0.24',
                       deprecated_hint='The semver for this option has already passed.')
      options.for_global_scope()

  @contextmanager
  def warnings_catcher(self):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter('always')
      yield w

  def test_deprecated_options(self):
    def assertWarning(w, option_string):
      self.assertEquals(1, len(w))
      self.assertTrue(issubclass(w[-1].category, DeprecationWarning))
      warning_message = str(w[-1].message)
      self.assertIn('is deprecated and will be removed', warning_message)
      self.assertIn(option_string, warning_message)

    with self.warnings_catcher() as w:
      options = self._parse('./pants --global-crufty=crufty1')
      self.assertEquals('crufty1', options.for_global_scope().global_crufty)
      assertWarning(w, 'global_crufty')

    with self.warnings_catcher() as w:
      options = self._parse('./pants --global-crufty-boolean')
      self.assertTrue(options.for_global_scope().global_crufty_boolean)
      assertWarning(w, 'global_crufty_boolean')

    with self.warnings_catcher() as w:
      options = self._parse('./pants --no-global-crufty-boolean')
      self.assertFalse(options.for_global_scope().global_crufty_boolean)
      assertWarning(w, 'global_crufty_boolean')

    with self.warnings_catcher() as w:
      options = self._parse('./pants stale --crufty=stale_and_crufty')
      self.assertEquals('stale_and_crufty', options.for_scope('stale').crufty)
      assertWarning(w, 'crufty')

    with self.warnings_catcher() as w:
      options = self._parse('./pants stale --crufty-boolean')
      self.assertTrue(options.for_scope('stale').crufty_boolean)
      assertWarning(w, 'crufty_boolean')

    with self.warnings_catcher() as w:
      options = self._parse('./pants stale --no-crufty-boolean')
      self.assertFalse(options.for_scope('stale').crufty_boolean)
      assertWarning(w, 'crufty_boolean')

    with self.warnings_catcher() as w:
      options = self._parse('./pants --no-stale-crufty-boolean')
      self.assertFalse(options.for_scope('stale').crufty_boolean)
      assertWarning(w, 'crufty_boolean')

    with self.warnings_catcher() as w:
      options = self._parse('./pants --stale-crufty-boolean')
      self.assertTrue(options.for_scope('stale').crufty_boolean)
      assertWarning(w, 'crufty_boolean')

    # Make sure the warnings don't come out for regular options.
    with self.warnings_catcher() as w:
      self._parse('./pants stale --pants-foo stale --still-good')
      self.assertEquals(0, len(w))

  def test_middle_scoped_options(self):
    """Make sure the rules for inheriting from a hierarchy of scopes.

    Values should follow
     1. A short circuit scan for a value from the following sources in-order:
        flags, env, config, hardcoded defaults
     2. Values for each source follow the . hierarchy scoping rule
        within that source.
    """

    # Short circuit using command line.
    options = self._parse('./pants --a=100 compile --a=99')
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    options = self._parse('./pants',
                          config={
                            'DEFAULT': {'a': 100},
                            'compile': {'a': 99},
                            })
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)

    # TODO(John Sirois): This should pick up 99 from the the recursive global '--a' flag defined in
    # middle scope 'compile', but instead it picks up `a`'s value from the config DEFAULT section.
    # Fix this test as part of https://github.com/pantsbuild/pants/issues/1803.
    self.assertEquals(100, options.for_scope('compile.java').a)

    options = self._parse('./pants',
                          env={
                            'PANTS_A': 100,
                            'PANTS_COMPILE_A': 99})
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    # Command line has precedence over config.
    options = self._parse('./pants compile --a=99',
                          config={
                            'DEFAULT': {'a': 100},
                            })
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    # Command line has precedence over environment.
    options = self._parse('./pants compile --a=99',
                          env={'PANTS_A': 100},)
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    # Env has precedence over config.
    options = self._parse('./pants ',
                          config={
                            'DEFAULT': {'a': 100},
                            },
                          env={'PANTS_COMPILE_A': 99},)
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    # Command line global overrides the middle scope setting in then env.
    options = self._parse('./pants --a=100',
                          env={'PANTS_COMPILE_A': 99},)
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(100, options.for_scope('compile').a)
    self.assertEquals(100, options.for_scope('compile.java').a)

    # Command line global overrides the middle scope in config.
    options = self._parse('./pants --a=100 ',
                          config={
                            'compile': {'a': 99},
                            })
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(100, options.for_scope('compile').a)
    self.assertEquals(100, options.for_scope('compile.java').a)

    # Env global overrides the middle scope in config.
    options = self._parse('./pants --a=100 ',
                          config={
                            'compile': {'a': 99},
                            },
                          env={'PANTS_A': 100},)
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(100, options.for_scope('compile').a)
    self.assertEquals(100, options.for_scope('compile.java').a)

  def test_complete_scopes(self):
    _global = GlobalOptionsRegistrar.get_scope_info()
    self.assertEquals({_global, intermediate('foo'), intermediate('foo.bar'), task('foo.bar.baz')},
                      Options.complete_scopes({task('foo.bar.baz')}))
    self.assertEquals({_global, intermediate('foo'), intermediate('foo.bar'), task('foo.bar.baz')},
                      Options.complete_scopes({GlobalOptionsRegistrar.get_scope_info(),
                                               task('foo.bar.baz')}))
    self.assertEquals({_global, intermediate('foo'), intermediate('foo.bar'), task('foo.bar.baz')},
                      Options.complete_scopes({intermediate('foo'), task('foo.bar.baz')}))
    self.assertEquals({_global, intermediate('foo'), intermediate('foo.bar'), task('foo.bar.baz'),
                       intermediate('qux'), task('qux.quux')},
                      Options.complete_scopes({task('foo.bar.baz'), task('qux.quux')}))

  def test_get_fingerprintable_for_scope(self):
    # Note: tests handling recursive and non-recursive options from enclosing scopes correctly.
    options = self._parse('./pants --store-true-flag --num=88 compile.scala --num=77 '
                          '--modifycompile="blah blah blah" --modifylogs="durrrr"')

    pairs = options.get_fingerprintable_for_scope('compile.scala')
    self.assertEquals(len(pairs), 3)
    self.assertEquals(('', 'blah blah blah'), pairs[0])
    self.assertEquals(('', True), pairs[1])
    self.assertEquals((int, 77), pairs[2])

  def assert_fromfile(self, parse_func, expected_append=None, append_contents=None):
    def _do_assert_fromfile(dest, expected, contents):
      with temporary_file() as fp:
        fp.write(contents)
        fp.close()
        options = parse_func(dest, fp.name)
        self.assertEqual(expected, options.for_scope('fromfile')[dest])

    _do_assert_fromfile(dest='string', expected='jake', contents='jake')
    _do_assert_fromfile(dest='intvalue', expected=42, contents='42')
    _do_assert_fromfile(dest='dictvalue', expected={'a': 42, 'b': (1, 2)}, contents=dedent("""
      {
        'a': 42,
        'b': (
          1,
          2
        )
      }
      """))
    _do_assert_fromfile(dest='listvalue', expected=['a', 1, 2], contents=dedent("""
      ['a',
       1,
       2]
      """))

    expected_append = expected_append or [1, 2, 42]
    append_contents = append_contents or dedent("""
      [
       1,
       2,
       42
      ]
      """)
    _do_assert_fromfile(dest='appendvalue', expected=expected_append, contents=append_contents)

  def test_fromfile_flags(self):
    def parse_func(dest, fromfile):
      return self._parse('./pants fromfile --{}=@{}'.format(dest.replace('_', '-'), fromfile))

    # You can only append a single item at a time with append flags, ie: we don't override the
    # default list like we do with env of config.  As such, send in a single append value here
    # instead of a whole default list as in `test_fromfile_config` and `test_fromfile_env`.
    self.assert_fromfile(parse_func, expected_append=[42], append_contents='42')

  def test_fromfile_config(self):
    def parse_func(dest, fromfile):
      return self._parse('./pants fromfile', config={'fromfile': {dest: '@{}'.format(fromfile)}})
    self.assert_fromfile(parse_func)

  def test_fromfile_env(self):
    def parse_func(dest, fromfile):
      return self._parse('./pants fromfile',
                         env={'PANTS_FROMFILE_{}'.format(dest.upper()): '@{}'.format(fromfile)})
    self.assert_fromfile(parse_func)

  def test_fromfile_error(self):
    options = self._parse('./pants fromfile --string=@/does/not/exist')
    with self.assertRaises(Parser.FromfileError):
      options.for_scope('fromfile')

  def test_fromfile_escape(self):
    options = self._parse(r'./pants fromfile --string=@@/does/not/exist')
    self.assertEqual('@/does/not/exist', options.for_scope('fromfile').string)

  def test_ranked_value_equality(self):
    none = RankedValue(RankedValue.NONE, None)
    some = RankedValue(RankedValue.HARDCODED, 'some')
    self.assertEquals('(NONE, None)', str(none))
    self.assertEquals('(HARDCODED, some)', str(some))
    self.assertNotEqual(some, none)
    self.assertEqual(some, RankedValue(RankedValue.HARDCODED, 'some'))
    self.assertNotEqual(some, RankedValue(RankedValue.HARDCODED, 'few'))
    self.assertNotEqual(some, RankedValue(RankedValue.CONFIG, 'some'))

  def test_option_tracker_required(self):
    with self.assertRaises(Options.OptionTrackerRequiredError):
      Options.create(None, None, [])
