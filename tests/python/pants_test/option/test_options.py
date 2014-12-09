# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import shlex
import unittest2 as unittest

from pants.option.options import Options
from pants_test.option.fake_config import FakeConfig


class OptionsTest(unittest.TestCase):
  _known_scopes = ['compile', 'compile.java', 'compile.scala', 'test', 'test.junit']

  def _register(self, options):
    options.register_global('-v', '--verbose', action='store_true', help='Verbose output.')
    options.register_global('-n', '--num', type=int, default=99)
    options.register_global('-x', '--xlong', action='store_true')
    options.register_global('--y', action='append', type=int)
    options.register_global('--pants-foo')
    options.register_global('--bar-baz')
    # Custom types.
    options.register_global('--dicty', type=Options.dict, default='{"a": "b"}')
    options.register_global('--listy', type=Options.list, default='[1, 2, 3]')

    # For the design doc example test.
    options.register_global('--a', type=int)
    options.register_global('--b', type=int)

    # Override --xlong with a different type (but leave -x alone).
    options.register('test', '--xlong', type=int)

    # For the design doc example test.
    options.register('compile', '--c', type=int)
    options.register('compile.java', '--b', type=str, default='foo')

  def _parse(self, args_str, env=None, config=None):
    args = shlex.split(str(args_str))
    options = Options(env or {}, FakeConfig(config or {}), OptionsTest._known_scopes, args)
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

