# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import shlex
import tempfile
import unittest
import warnings
from contextlib import contextmanager
from textwrap import dedent

from pants.base.deprecated import PastRemovalVersionError
from pants.option.errors import ParseError
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.parser import Parser
from pants.option.scope import ScopeInfo
from pants_test.option.fake_config import FakeConfig


def goal(scope):
  return ScopeInfo(scope, ScopeInfo.GOAL)


def task(scope):
  return ScopeInfo(scope, ScopeInfo.TASK)


def intermediate(scope):
  return ScopeInfo(scope, ScopeInfo.INTERMEDIATE)


class OptionsTest(unittest.TestCase):
  _known_scope_infos = [goal('compile'), task('compile.java'), task('compile.scala'),
                        goal('stale'), goal('test'), task('test.junit')]

  def _register(self, options):
    def register_global(*args, **kwargs):
      options.register(Options.GLOBAL_SCOPE, *args, **kwargs)

    register_global('-v', '--verbose', action='store_true', help='Verbose output.', recursive=True)
    register_global('-n', '--num', type=int, default=99, recursive=True)
    register_global('-x', '--xlong', action='store_true', recursive=True)
    register_global('--y', action='append', type=int)
    register_global('--pants-foo')
    register_global('--bar-baz')
    register_global('--store-true-flag', action='store_true')
    register_global('--store-false-flag', action='store_false')
    register_global('--store-true-def-true-flag', action='store_true', default=True)
    register_global('--store-true-def-false-flag', action='store_true', default=False)
    register_global('--store-false-def-false-flag', action='store_false', default=False)
    register_global('--store-false-def-true-flag', action='store_false', default=True)

    # Custom types.
    register_global('--dicty', type=Options.dict, default='{"a": "b"}')
    register_global('--listy', type=Options.list, default='[1, 2, 3]')

    # For the design doc example test.
    register_global('--a', type=int, recursive=True)
    register_global('--b', type=int, recursive=True)

    # Deprecated global options
    register_global('--global-crufty', deprecated_version='999.99.9',
                    deprecated_hint='use a less crufty global option')
    register_global('--global-crufty-boolean', action='store_true', deprecated_version='999.99.9',
                    deprecated_hint='say no to crufty global options')

    # Override --xlong with a different type (but leave -x alone).
    options.register('test', '--xlong', type=int)

    # For the design doc example test.
    options.register('compile', '--c', type=int, recursive=True)
    options.register('compile.java', '--b', type=str, default='foo')

    # Test deprecated options with a scope
    options.register('stale', '--still-good')
    options.register('stale', '--crufty',
                     deprecated_version='999.99.9',
                     deprecated_hint='use a less crufty stale scoped option')
    options.register('stale', '--crufty-boolean', action='store_true',
                     deprecated_version='999.99.9',
                     deprecated_hint='say no to crufty, stale scoped options')

  def _parse(self, args_str, env=None, config=None, bootstrap_option_values=None):
    args = shlex.split(str(args_str))
    options = Options(env or {}, FakeConfig(config or {}), OptionsTest._known_scope_infos, args,
                      bootstrap_option_values=bootstrap_option_values)
    self._register(options)
    return options

  def test_arg_scoping(self):
    # Some basic smoke tests.
    options = self._parse('./pants --verbose')
    self.assertEqual(True, options.for_global_scope().verbose)
    self.assertEqual(True, options.for_global_scope().v)
    options = self._parse('./pants -v compile tgt')
    self.assertEqual(['tgt'], options.target_specs)
    self.assertEqual(True, options.for_global_scope().verbose)
    self.assertEqual(True, options.for_global_scope().v)

    # Scoping of different values of the same option.
    # Also tests the --no-* boolean flag inverses.
    options = self._parse('./pants --verbose compile.java --no-verbose')
    self.assertEqual(True, options.for_global_scope().verbose)
    self.assertEqual(True, options.for_scope('compile').verbose)
    self.assertEqual(False, options.for_scope('compile.java').verbose)

    options = self._parse('./pants --verbose compile --no-verbose compile.java -v test '
                          'test.junit --no-verbose')
    self.assertEqual(True, options.for_global_scope().verbose)
    self.assertEqual(False, options.for_scope('compile').verbose)
    self.assertEqual(True, options.for_scope('compile.java').verbose)
    self.assertEqual(True, options.for_scope('test').verbose)
    self.assertEqual(False, options.for_scope('test.junit').verbose)

    # Proper shadowing of a re-registered flag.  The flag's -x alias retains its old meaning.
    options = self._parse('./pants --no-xlong test --xlong=100 -x')
    self.assertEqual(False, options.for_global_scope().xlong)
    self.assertEqual(False, options.for_global_scope().x)
    self.assertEqual(100, options.for_scope('test').xlong)
    self.assertEqual(True, options.for_scope('test').x)

    # Test action=append option.
    options = self._parse('./pants', config={ 'DEFAULT': { 'y': ['88', '-99'] }})
    self.assertEqual([88, -99], options.for_global_scope().y)

    options = self._parse('./pants --y=5 --y=-6 --y=77',
                          config={ 'DEFAULT': { 'y': ['88', '-99'] }})
    self.assertEqual([88, -99, 5, -6, 77], options.for_global_scope().y)

    # Test list-typed option.
    options = self._parse('./pants --listy=\'["c", "d"]\'',
                          config={ 'DEFAULT': {'listy': ["a", "b"] }})
    self.assertEqual(['c', 'd'], options.for_global_scope().listy)

    # Test dict-typed option.
    options = self._parse('./pants --dicty=\'{"c": "d"}\'')
    self.assertEqual({'c': 'd'}, options.for_global_scope().dicty)

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
                          + ' --store-true-def-true-flag --store-true-def-false-flag '
                          + ' --store-false-def-true-flag --store-false-def-false-flag')

    self.assertTrue(options.for_global_scope().store_true_flag)
    self.assertFalse(options.for_global_scope().store_false_flag)
    self.assertTrue(options.for_global_scope().store_true_def_false_flag)
    self.assertTrue(options.for_global_scope().store_true_def_true_flag)
    self.assertFalse(options.for_global_scope().store_false_def_false_flag)
    self.assertFalse(options.for_global_scope().store_false_def_true_flag)

  def test_boolean_negate_option(self):
    options = self._parse('./pants --no-store-true-flag --no-store-false-flag '
                          + ' --no-store-true-def-true-flag --no-store-true-def-false-flag '
                          + ' --no-store-false-def-true-flag --no-store-false-def-false-flag')
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
                                                 }})
    with self.assertRaises(Parser.BooleanConversionError):
      self._parse('./pants', config={'DEFAULT': {'store_true_flag': 'AlmostTrue',
                                               }})

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
      'DEFAULT': { 'num': '88' },
      'compile': { 'num': '77' },
      'compile.java': { 'num': '66' }
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

  def test_recursion(self):
    # Recursive option.
    options = self._parse('./pants -n=5 compile -n=6')
    self.assertEqual(5, options.for_global_scope().n)
    self.assertEqual(6, options.for_scope('compile').n)

    # Non-recursive option.
    options = self._parse('./pants --bar-baz=foo')
    self.assertEqual('foo', options.for_global_scope().bar_baz)
    options = self._parse('./pants compile --bar-baz=foo')
    with self.assertRaises(ParseError):
      options.for_scope('compile').bar_baz

  def test_is_known_scope(self):
    options = self._parse('./pants')
    for scope_info in self._known_scope_infos:
      self.assertTrue(options.is_known_scope(scope_info.scope))
    self.assertFalse(options.is_known_scope('nonexistent_scope'))

  def test_designdoc_example(self):
    # The example from the design doc.
    # Get defaults from config and environment.
    config = {
      'DEFAULT': { 'b': '99' },
      'compile': { 'a': '88', 'c': '77' },
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
    self.assertEqual('foo', options.for_scope('compile.java').b)
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
      cmdline = './pants --target-spec-file={filename} compile morx fleem'.format(filename=tmp.name)
      bootstrapper = OptionsBootstrapper(args=shlex.split(cmdline))
      bootstrap_options = bootstrapper.get_bootstrap_options().for_global_scope()
      options = self._parse(cmdline, bootstrap_option_values=bootstrap_options)
      sorted_specs = sorted(options.target_specs)
      self.assertEqual(['bar', 'fleem', 'foo', 'morx'], sorted_specs)

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

  def test_deprecated_option_past_removal(self):
    with self.assertRaises(PastRemovalVersionError):
      options = Options({}, FakeConfig({}), OptionsTest._known_scope_infos, "./pants")
      options.register(Options.GLOBAL_SCOPE, '--too-old-option', deprecated_version='0.0.24',
                              deprecated_hint='The semver for this option has already passed.')

  @contextmanager
  def warnings_catcher(self):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      yield w

  def test_deprecated_options(self):
    def assertWarning(w, option_string):
      self.assertEquals(1, len(w))
      self.assertTrue(issubclass(w[-1].category, DeprecationWarning))
      warning_message = str(w[-1].message)
      self.assertIn("is deprecated and will be removed", warning_message)
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

    # Make sure the warnings don't come out for regular options
    with self.warnings_catcher() as w:
      self._parse('./pants stale --pants-foo stale --still-good')
      self.assertEquals(0, len(w))

  def test_middle_scoped_options(self):
    """
    Make sure the rules for inheriting from a hierarchy of scopes.

    Values should follow
     1. A short circuit scan for a value from the following sources in-order:
        flags, env, config, hardcoded defaults
     2. Values for each source follow the . hierarchy scoping rule
        within that source.
    """

    # Short circuit using command line
    options = self._parse('./pants --a=100 compile --a=99')
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    options=self._parse('./pants',
                        config={
                          'DEFAULT': {'a' : 100},
                          'compile': {'a' : 99},
                          })
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    options=self._parse('./pants',
                        env={
                          'PANTS_A': 100,
                          'PANTS_COMPILE_A' : 99})
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    # Command line has precedence over config
    options=self._parse('./pants compile --a=99',
                        config={
                          'DEFAULT': {'a' : 100},
                          })
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    # Command line has precedence over environment
    options=self._parse('./pants compile --a=99',
                        env={'PANTS_A':  100},)
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    # Env has precedence over config
    options=self._parse('./pants ',
                        config={
                          'DEFAULT': {'a' : 100},
                          },
                        env={'PANTS_COMPILE_A':  99},)
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    # Command line global overrides the middle scope setting in then env
    options=self._parse('./pants --a=100',
                        env={'PANTS_COMPILE_A':  99},)
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(100, options.for_scope('compile').a)
    self.assertEquals(100, options.for_scope('compile.java').a)

    # Command line global overrides the middle scope in config
    options = self._parse('./pants --a=100 ',
                          config={
                            'compile': {'a' : 99},
                            })
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(100, options.for_scope('compile').a)
    self.assertEquals(100, options.for_scope('compile.java').a)

    # Env global overrides the middle scope in config
    options = self._parse('./pants --a=100 ',
                          config={
                            'compile': {'a' : 99},
                            },
                          env={'PANTS_A':  100},)
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(100, options.for_scope('compile').a)
    self.assertEquals(100, options.for_scope('compile.java').a)

  def test_complete_scopes(self):
    _global = ScopeInfo.for_global_scope()
    self.assertEquals({_global, intermediate('foo'), intermediate('foo.bar'), task('foo.bar.baz')},
                      Options.complete_scopes({task('foo.bar.baz')}))
    self.assertEquals({_global, intermediate('foo'), intermediate('foo.bar'), task('foo.bar.baz')},
                      Options.complete_scopes({ScopeInfo.for_global_scope(), task('foo.bar.baz')}))
    self.assertEquals({_global, goal('foo'), intermediate('foo.bar'), task('foo.bar.baz')},
                      Options.complete_scopes({goal('foo'), task('foo.bar.baz')}))
    self.assertEquals({_global, intermediate('foo'), intermediate('foo.bar'), task('foo.bar.baz'),
                       intermediate('qux'), task('qux.quux')},
                      Options.complete_scopes({task('foo.bar.baz'), task('qux.quux')}))
