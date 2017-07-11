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

from pants.base.deprecated import CodeRemovedError
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.config import Config
from pants.option.custom_types import UnsetBool, file_option, target_option
from pants.option.errors import (BooleanOptionNameWithNo, FrozenRegistration, ImplicitValIsNone,
                                 InvalidKwarg, InvalidMemberType, MemberTypeNotAllowed,
                                 NoOptionNames, OptionAlreadyRegistered, OptionNameDash,
                                 OptionNameDoubleDash, ParseError, RecursiveSubsystemOption,
                                 Shadowing)
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.option_tracker import OptionTracker
from pants.option.optionable import Optionable
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

    register_global('-z', '--verbose', type=bool, help='Verbose output.', recursive=True)
    register_global('-n', '--num', type=int, default=99, recursive=True, fingerprint=True)
    register_global('--y', type=list, member_type=int)
    register_global('--config-override', type=list)

    register_global('--pants-foo')
    register_global('--bar-baz')
    register_global('--store-true-flag', type=bool, fingerprint=True)
    register_global('--store-false-flag', type=bool, implicit_value=False)
    register_global('--store-true-def-true-flag', type=bool, default=True)
    register_global('--store-true-def-false-flag', type=bool, default=False)
    register_global('--store-false-def-false-flag', type=bool, implicit_value=False, default=False)
    register_global('--store-false-def-true-flag', type=bool, implicit_value=False, default=True)
    register_global('--def-unset-bool-flag', type=bool, default=UnsetBool)

    # Choices.
    register_global('--str-choices', choices=['foo', 'bar'])
    register_global('--int-choices', choices=[42, 99], type=list, member_type=int)

    # Custom types.
    register_global('--listy', type=list, member_type=int, default='[1, 2, 3]')
    register_global('--dicty', type=dict, default='{"a": "b"}')
    register_global('--dict-listy', type=list, member_type=dict,
                    default='[{"a": 1, "b": 2}, {"c": 3}]')
    register_global('--targety', type=target_option, default='//:a')
    register_global('--target-listy', type=list, member_type=target_option,
                    default=['//:a', '//:b'])
    register_global('--filey', type=file_option, default=None)
    register_global('--file-listy', type=list, member_type=file_option)

    # Implicit value.
    register_global('--implicit-valuey', default='default', implicit_value='implicit')

    # For the design doc example test.
    register_global('--a', type=int, recursive=True)
    register_global('--b', type=int, recursive=True)

    # Deprecated global options
    register_global('--global-crufty', removal_version='999.99.9.dev0',
                    removal_hint='use a less crufty global option')
    register_global('--global-crufty-boolean', type=bool, removal_version='999.99.9.dev0',
                      removal_hint='say no to crufty global options')
    register_global('--global-crufty-expired', removal_version='0.0.1.dev0',
                    removal_hint='use a less crufty global option')

    # Mutual Exclusive options
    register_global('--mutex-foo', mutually_exclusive_group='mutex')
    register_global('--mutex-bar', mutually_exclusive_group='mutex')
    register_global('--mutex-baz', mutually_exclusive_group='mutex')

    register_global('--new-name')
    register_global('--old-name', mutually_exclusive_group='new_name')

    # For the design doc example test.
    options.register('compile', '--c', type=int, recursive=True)

    # Test deprecated options with a scope
    options.register('stale', '--still-good')
    options.register('stale', '--crufty',
                     removal_version='999.99.9.dev0',
                     removal_hint='use a less crufty stale scoped option')
    options.register('stale', '--crufty-boolean', type=bool,
                     removal_version='999.99.9.dev0',
                     removal_hint='say no to crufty, stale scoped options')

    # Test mutual exclusive options with a scope
    options.register('stale', '--mutex-a', mutually_exclusive_group='crufty_mutex')
    options.register('stale', '--mutex-b', mutually_exclusive_group='crufty_mutex')
    options.register('stale', '--crufty-old', mutually_exclusive_group='crufty_new')
    options.register('stale', '--crufty-new')

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
    options.register('fromfile', '--dictvalue', type=dict, fromfile=True)
    options.register('fromfile', '--listvalue', type=list, fromfile=True)
    options.register('fromfile', '--appendvalue', type=list, member_type=int, fromfile=True)

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

  def test_env_type_int(self):
    options = Options.create(env={'PANTS_FOO_BAR': "['123','456']"},
                             config=self._create_config({}),
                             known_scope_infos=OptionsTest._known_scope_infos,
                             args=shlex.split('./pants'),
                             option_tracker=OptionTracker())
    options.register(GLOBAL_SCOPE, '--foo-bar', type=list, member_type=int)
    self.assertEqual([123, 456], options.for_global_scope().foo_bar)

    options = Options.create(env={'PANTS_FOO_BAR': '123'},
                             config=self._create_config({}),
                             known_scope_infos=OptionsTest._known_scope_infos,
                             args=shlex.split('./pants'),
                             option_tracker=OptionTracker())
    options.register(GLOBAL_SCOPE, '--foo-bar', type=int)
    self.assertEqual(123, options.for_global_scope().foo_bar)

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

    # Test list-typed option.
    options = self._parse('./pants', config={'DEFAULT': {'y': ['88', '-99']}})
    self.assertEqual([88, -99], options.for_global_scope().y)

    options = self._parse('./pants --y=5 --y=-6 --y=77',
                          config={'DEFAULT': {'y': ['88', '-99']}})
    self.assertEqual([88, -99, 5, -6, 77], options.for_global_scope().y)

    options = self._parse('./pants')
    self.assertEqual([], options.for_global_scope().y)

    options = self._parse('./pants ', env={'PANTS_CONFIG_OVERRIDE': "['123','456']"})
    self.assertEqual(['123', '456'], options.for_global_scope().config_override)

    options = self._parse('./pants ', env={'PANTS_CONFIG_OVERRIDE': "['']"})
    self.assertEqual([''], options.for_global_scope().config_override)

    options = self._parse('./pants --listy=\'[1, 2]\'',
                          config={'DEFAULT': {'listy': '[3, 4]'}})
    self.assertEqual([1, 2], options.for_global_scope().listy)

    # Test dict-typed option.
    options = self._parse('./pants --dicty=\'{"c": "d"}\'')
    self.assertEqual({'c': 'd'}, options.for_global_scope().dicty)

    # Test list-of-dict-typed option.
    options = self._parse('./pants --dict-listy=\'[{"c": "d"}, {"e": "f"}]\'')
    self.assertEqual([{'c': 'd'}, {'e': 'f'}], options.for_global_scope().dict_listy)

    # Test target-typed option.
    options = self._parse('./pants')
    self.assertEqual('//:a', options.for_global_scope().targety)
    options = self._parse('./pants --targety=//:foo')
    self.assertEqual('//:foo', options.for_global_scope().targety)

    # Test list-of-target-typed option.
    options = self._parse('./pants --target-listy=\'["//:foo", "//:bar"]\'')
    self.assertEqual(['//:foo', '//:bar'], options.for_global_scope().target_listy)

    # Test file-typed option.
    with temporary_file_path() as fp:
      options = self._parse('./pants --filey="{}"'.format(fp))
      self.assertEqual(fp, options.for_global_scope().filey)

    # Test list-of-file-typed option.
    with temporary_file_path() as fp1:
      with temporary_file_path() as fp2:
        options = self._parse('./pants --file-listy="{}" --file-listy="{}"'.format(fp1, fp2))
        self.assertEqual([fp1, fp2], options.for_global_scope().file_listy)

  def test_explicit_boolean_values(self):
    options = self._parse('./pants --verbose=false')
    self.assertFalse(options.for_global_scope().verbose)
    options = self._parse('./pants --verbose=False')
    self.assertFalse(options.for_global_scope().verbose)

    options = self._parse('./pants --verbose=true')
    self.assertTrue(options.for_global_scope().verbose)
    options = self._parse('./pants --verbose=True')
    self.assertTrue(options.for_global_scope().verbose)

  def test_boolean_defaults(self):
    options = self._parse('./pants')
    self.assertFalse(options.for_global_scope().store_true_flag)
    self.assertTrue(options.for_global_scope().store_false_flag)
    self.assertFalse(options.for_global_scope().store_true_def_false_flag)
    self.assertTrue(options.for_global_scope().store_true_def_true_flag)
    self.assertFalse(options.for_global_scope().store_false_def_false_flag)
    self.assertTrue(options.for_global_scope().store_false_def_true_flag)
    self.assertIsNone(options.for_global_scope().def_unset_bool_flag)

  def test_boolean_set_option(self):
    options = self._parse('./pants --store-true-flag --store-false-flag '
                          ' --store-true-def-true-flag --store-true-def-false-flag '
                          ' --store-false-def-true-flag --store-false-def-false-flag '
                          ' --def-unset-bool-flag')

    self.assertTrue(options.for_global_scope().store_true_flag)
    self.assertFalse(options.for_global_scope().store_false_flag)
    self.assertTrue(options.for_global_scope().store_true_def_false_flag)
    self.assertTrue(options.for_global_scope().store_true_def_true_flag)
    self.assertFalse(options.for_global_scope().store_false_def_false_flag)
    self.assertFalse(options.for_global_scope().store_false_def_true_flag)
    self.assertTrue(options.for_global_scope().def_unset_bool_flag)

  def test_boolean_negate_option(self):
    options = self._parse('./pants --no-store-true-flag --no-store-false-flag '
                          ' --no-store-true-def-true-flag --no-store-true-def-false-flag '
                          ' --no-store-false-def-true-flag --no-store-false-def-false-flag '
                          ' --no-def-unset-bool-flag')
    self.assertFalse(options.for_global_scope().store_true_flag)
    self.assertTrue(options.for_global_scope().store_false_flag)
    self.assertFalse(options.for_global_scope().store_true_def_false_flag)
    self.assertFalse(options.for_global_scope().store_true_def_true_flag)
    self.assertTrue(options.for_global_scope().store_false_def_false_flag)
    self.assertTrue(options.for_global_scope().store_false_def_true_flag)
    self.assertFalse(options.for_global_scope().def_unset_bool_flag)

  def test_boolean_config_override_true(self):
    options = self._parse('./pants', config={'DEFAULT': {'store_true_flag': True,
                                                         'store_false_flag': True,
                                                         'store_true_def_true_flag': True,
                                                         'store_true_def_false_flag': True,
                                                         'store_false_def_true_flag': True,
                                                         'store_false_def_false_flag': True,
                                                         'def_unset_bool_flag': True,
                                                         }})
    self.assertTrue(options.for_global_scope().store_true_flag)
    self.assertTrue(options.for_global_scope().store_false_flag)
    self.assertTrue(options.for_global_scope().store_true_def_false_flag)
    self.assertTrue(options.for_global_scope().store_true_def_true_flag)
    self.assertTrue(options.for_global_scope().store_false_def_false_flag)
    self.assertTrue(options.for_global_scope().store_false_def_true_flag)
    self.assertTrue(options.for_global_scope().def_unset_bool_flag)

  def test_boolean_config_override_false(self):
    options = self._parse('./pants', config={'DEFAULT': {'store_true_flag': False,
                                                         'store_false_flag': False,
                                                         'store_true_def_true_flag': False,
                                                         'store_true_def_false_flag': False,
                                                         'store_false_def_true_flag': False,
                                                         'store_false_def_false_flag': False,
                                                         'def_unset_bool_flag': False,
                                                         }})
    self.assertFalse(options.for_global_scope().store_true_flag)
    self.assertFalse(options.for_global_scope().store_false_flag)
    self.assertFalse(options.for_global_scope().store_true_def_false_flag)
    self.assertFalse(options.for_global_scope().store_true_def_true_flag)
    self.assertFalse(options.for_global_scope().store_false_def_false_flag)
    self.assertFalse(options.for_global_scope().store_false_def_true_flag)
    self.assertFalse(options.for_global_scope().def_unset_bool_flag)

  def test_boolean_invalid_value(self):
    with self.assertRaises(Parser.BooleanConversionError):
      self._parse('./pants', config={'DEFAULT': {'store_true_flag': 11,
                                                 }}).for_global_scope()
    with self.assertRaises(Parser.BooleanConversionError):
      self._parse('./pants', config={'DEFAULT': {'store_true_flag': 'AlmostTrue',
                                                 }}).for_global_scope()

  def test_list_option(self):
    def check(expected, args_str, env=None, config=None):
      options = self._parse(args_str=args_str, env=env, config=config)
      self.assertEqual(expected, options.for_global_scope().listy)

    # Appending to the default.
    check([1, 2, 3, 4], './pants --listy=4')
    check([1, 2, 3, 4, 5], './pants --listy=4 --listy=5')
    check([1, 2, 3, 4, 5], './pants --listy=+[4,5]')

    # Filtering from the default.
    check([1, 3], './pants --listy=-[2]')

    # Replacing the default.
    check([4, 5], './pants --listy=[4,5]')

    # Appending across env, config and flags (in the right order).
    check([1, 2, 3, 4, 5, 6, 7, 8, 9], './pants --listy=+[8,9]',
          env={'PANTS_GLOBAL_LISTY': '+[6,7]'},
          config={'GLOBAL': {'listy': '+[4,5]'}})

    # Appending and filtering across env, config and flags (in the right order).
    check([2, 3, 4, 7], './pants --listy=-[1,5,6]',
          env={'PANTS_GLOBAL_LISTY': '+[6,7]'},
          config={'GLOBAL': {'listy': '+[4,5]'}})

    check([1, 2, 8, 9], './pants --listy=+[8,9]',
          env={'PANTS_GLOBAL_LISTY': '-[4,5]'},
          config={'GLOBAL': {'listy': '+[4,5],-[3]'}})

    # Overwriting from env, then appending and filtering.
    check([7, 8, 9], './pants --listy=+[8,9],-[6]',
          env={'PANTS_GLOBAL_LISTY': '[6,7]'},
          config={'GLOBAL': {'listy': '+[4,5]'}})

    # Overwriting from config, then appending.
    check([4, 5, 6, 7, 8, 9], './pants --listy=+[8,9]',
          env={'PANTS_GLOBAL_LISTY': '+[6,7]'},
          config={'GLOBAL': {'listy': '[4,5]'}})

    # Overwriting from flags.
    check([8, 9], './pants --listy=[8,9]',
          env={'PANTS_GLOBAL_LISTY': '+[6,7]'},
          config={'GLOBAL': {'listy': '+[4,5],-[8]'}})

    # Filtering all instances of repeated values.
    check([1, 2, 3, 4, 6], './pants --listy=-[5]',
          config={'GLOBAL': {'listy': '[1, 2, 5, 3, 4, 5, 6, 5, 5]'}})

    # Filtering a value even though it was appended again at a higher rank.
    check([1, 2, 3, 5], './pants --listy=+[4]',
          env={'PANTS_GLOBAL_LISTY': '-[4]'},
          config={'GLOBAL': {'listy': '+[4, 5]'}})

    # Filtering a value even though it was appended again at the same rank.
    check([1, 2, 3, 5], './pants',
          env={'PANTS_GLOBAL_LISTY': '-[4],+[4]'},
          config={'GLOBAL': {'listy': '+[4, 5]'}})

    # Overwriting cancels filters.
    check([4], './pants',
          env={'PANTS_GLOBAL_LISTY': '[4]'},
          config={'GLOBAL': {'listy': '-[4]'}})

  def test_dict_list_option(self):
    def check(expected, args_str, env=None, config=None):
      options = self._parse(args_str=args_str, env=env, config=config)
      self.assertEqual(expected, options.for_global_scope().dict_listy)

    # Appending to the default.
    check([{'a': 1, 'b': 2}, {'c': 3}], './pants')
    check([{'a': 1, 'b': 2}, {'c': 3}, {'d': 4, 'e': 5}],
          './pants --dict-listy=\'{"d": 4, "e": 5}\'')
    check([{'a': 1, 'b': 2}, {'c': 3}, {'d': 4, 'e': 5}, {'f': 6}],
          './pants --dict-listy=\'{"d": 4, "e": 5}\' --dict-listy=\'{"f": 6}\'')
    check([{'a': 1, 'b': 2}, {'c': 3}, {'d': 4, 'e': 5}, {'f': 6}],
          './pants --dict-listy=\'+[{"d": 4, "e": 5}, {"f": 6}]\'')

    # Replacing the default.
    check([{'d': 4, 'e': 5}, {'f': 6}],
          './pants --dict-listy=\'[{"d": 4, "e": 5}, {"f": 6}]\'')

    # Parsing env var correctly.
    check([{'a': 1, 'b': 2}, {'c': 3}, {'d': 4, 'e': 5}],
          './pants', env={'PANTS_GLOBAL_DICT_LISTY': '{"d": 4, "e": 5}'})
    check([{'a': 1, 'b': 2}, {'c': 3}, {'d': 4, 'e': 5}, {'f': 6}],
          './pants', env={'PANTS_GLOBAL_DICT_LISTY': '+[{"d": 4, "e": 5}, {"f": 6}]'})
    check([{'d': 4, 'e': 5}, {'f': 6}],
          './pants', env={'PANTS_GLOBAL_DICT_LISTY': '[{"d": 4, "e": 5}, {"f": 6}]'})

    # Parsing config value correctly.
    check([{'a': 1, 'b': 2}, {'c': 3}, {'d': 4, 'e': 5}],
          './pants', config={'GLOBAL': { 'dict_listy': '{"d": 4, "e": 5}'} })
    check([{'a': 1, 'b': 2}, {'c': 3}, {'d': 4, 'e': 5}, {'f': 6}],
          './pants', config={'GLOBAL': { 'dict_listy': '+[{"d": 4, "e": 5}, {"f": 6}]'} })
    check([{'d': 4, 'e': 5}, {'f': 6}],
          './pants', config={'GLOBAL': { 'dict_listy': '[{"d": 4, "e": 5}, {"f": 6}]'} })

  def test_target_list_option(self):
    def check(expected, args_str, env=None, config=None):
      options = self._parse(args_str=args_str, env=env, config=config)
      self.assertEqual(expected, options.for_global_scope().target_listy)

    # Appending to the default.
    check(['//:a', '//:b'], './pants')
    check(['//:a', '//:b', '//:c', '//:d'],
          './pants --target-listy=//:c --target-listy=//:d')
    check(['//:a', '//:b', '//:c', '//:d'],
          './pants --target-listy=\'+["//:c", "//:d"]\'')

    # Replacing the default.
    check(['//:c', '//:d'],
          './pants --target-listy=\'["//:c", "//:d"]\'')

    # Parsing env var correctly.
    check(['//:a', '//:b', '//:c'],
          './pants', env={'PANTS_GLOBAL_TARGET_LISTY': '//:c'})
    check(['//:a', '//:b', '//:c', '//:d'],
          './pants', env={'PANTS_GLOBAL_TARGET_LISTY': '+["//:c", "//:d"]'})
    check(['//:c', '//:d'],
          './pants', env={'PANTS_GLOBAL_TARGET_LISTY': '["//:c", "//:d"]'})

    # Parsing config value correctly.
    check(['//:a', '//:b', '//:c'],
          './pants', config={'GLOBAL': {'target_listy': '//:c'} })
    check(['//:a', '//:b', '//:c', '//:d'],
          './pants', config={'GLOBAL': {'target_listy': '+["//:c", "//:d"]'} })
    check(['//:c', '//:d'],
          './pants', config={'GLOBAL': {'target_listy': '["//:c", "//:d"]'} })

  def test_dict_option(self):
    def check(expected, args_str, env=None, config=None):
      options = self._parse(args_str=args_str, env=env, config=config)
      self.assertEqual(expected, options.for_global_scope().dicty)

    check({'a': 'b'}, './pants')
    check({'c': 'd'}, './pants --dicty=\'{"c": "d"}\'')
    check({'a': 'b', 'c': 'd'}, './pants --dicty=\'+{"c": "d"}\'')

    check({'c': 'd'}, './pants', config={'GLOBAL': {'dicty': '{"c": "d"}'}})
    check({'a': 'b', 'c': 'd'}, './pants', config={'GLOBAL': {'dicty': '+{"c": "d"}'}})
    check({'a': 'b', 'c': 'd', 'e': 'f'}, './pants --dicty=\'+{"e": "f"}\'',
          config={'GLOBAL': {'dicty': '+{"c": "d"}'}})

    # Check that highest rank wins if we have multiple values for the same key.
    check({'a': 'b+', 'c': 'd'}, './pants', config={'GLOBAL': {'dicty': '+{"a": "b+", "c": "d"}'}})
    check({'a': 'b++', 'c': 'd'}, './pants --dicty=\'+{"a": "b++"}\'',
          config={'GLOBAL': {'dicty': '+{"a": "b+", "c": "d"}'}})

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
    assertError(InvalidKwarg, '--foo', badkwarg=42)
    assertError(ImplicitValIsNone, '--foo', implicit_value=None)
    assertError(BooleanOptionNameWithNo, '--no-foo', type=bool)
    assertError(MemberTypeNotAllowed, '--foo', member_type=int)
    assertError(MemberTypeNotAllowed, '--foo', type=dict, member_type=int)
    assertError(InvalidMemberType, '--foo', type=list, member_type=set)
    assertError(InvalidMemberType, '--foo', type=list, member_type=list)
    assertError(InvalidMemberType, '--foo', type=list, member_type=list)

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
      options.for_global_scope().c

    self.assertEqual(1, options.for_scope('compile').a)
    self.assertEqual(2, options.for_scope('compile').b)
    self.assertEqual(66, options.for_scope('compile').c)

    self.assertEqual(3, options.for_scope('compile.java').a)
    self.assertEqual(2, options.for_scope('compile.java').b)
    self.assertEqual(4, options.for_scope('compile.java').c)

  def test_file_spec_args(self):
    with tempfile.NamedTemporaryFile() as tmp:
      tmp.write(dedent(
        """
        foo
        bar
        """
      ))
      tmp.flush()
      # Note that we prevent loading a real pants.ini during get_bootstrap_options().
      cmdline = './pants --target-spec-file={filename} --pants-config-files="[]" ' \
                'compile morx:tgt fleem:tgt'.format(
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
      'PANTS_GLOBAL_PANTS_FOO': 'AAA',
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
      'PANTS_GLOBAL_BAR_BAZ': 'AAA',
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
    """Ensure that expired options raise CodeRemovedError on attempted use."""
    # Test option past removal from flag
    with self.assertRaises(CodeRemovedError):
      self._parse('./pants --global-crufty-expired=way2crufty').for_global_scope()

    # Test option past removal from env
    with self.assertRaises(CodeRemovedError):
      self._parse('./pants', env={'PANTS_GLOBAL_CRUFTY_EXPIRED':'way2crufty'}).for_global_scope()

    #Test option past removal from config
    with self.assertRaises(CodeRemovedError):
      self._parse('./pants', config={'GLOBAL':{'global_crufty_expired':'way2crufty'}}).for_global_scope()

  @contextmanager
  def warnings_catcher(self):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter('always')
      yield w

  def assertWarning(self, w, option_string):
    self.assertEquals(1, len(w))
    self.assertTrue(issubclass(w[-1].category, DeprecationWarning))
    warning_message = str(w[-1].message)
    self.assertIn("will be removed in version",
                  warning_message)
    self.assertIn(option_string, warning_message)

  def test_deprecated_options_flag(self):
    with self.warnings_catcher() as w:
      options = self._parse('./pants --global-crufty=crufty1')
      self.assertEquals('crufty1', options.for_global_scope().global_crufty)
      self.assertWarning(w, 'global_crufty')

    with self.warnings_catcher() as w:
      options = self._parse('./pants --global-crufty-boolean')
      self.assertTrue(options.for_global_scope().global_crufty_boolean)
      self.assertWarning(w, 'global_crufty_boolean')

    with self.warnings_catcher() as w:
      options = self._parse('./pants --no-global-crufty-boolean')
      self.assertFalse(options.for_global_scope().global_crufty_boolean)
      self.assertWarning(w, 'global_crufty_boolean')

    with self.warnings_catcher() as w:
      options = self._parse('./pants stale --crufty=stale_and_crufty')
      self.assertEquals('stale_and_crufty', options.for_scope('stale').crufty)
      self.assertWarning(w, 'crufty')

    with self.warnings_catcher() as w:
      options = self._parse('./pants stale --crufty-boolean')
      self.assertTrue(options.for_scope('stale').crufty_boolean)
      self.assertWarning(w, 'crufty_boolean')

    with self.warnings_catcher() as w:
      options = self._parse('./pants stale --no-crufty-boolean')
      self.assertFalse(options.for_scope('stale').crufty_boolean)
      self.assertWarning(w, 'crufty_boolean')

    with self.warnings_catcher() as w:
      options = self._parse('./pants --no-stale-crufty-boolean')
      self.assertFalse(options.for_scope('stale').crufty_boolean)
      self.assertWarning(w, 'crufty_boolean')

    with self.warnings_catcher() as w:
      options = self._parse('./pants --stale-crufty-boolean')
      self.assertTrue(options.for_scope('stale').crufty_boolean)
      self.assertWarning(w, 'crufty_boolean')

    # Make sure the warnings don't come out for regular options.
    with self.warnings_catcher() as w:
      self._parse('./pants stale --pants-foo stale --still-good')
      self.assertEquals(0, len(w))

  def test_deprecated_options_env(self):
    with self.warnings_catcher() as w:
      options = self._parse('./pants', env={'PANTS_GLOBAL_CRUFTY':'crufty1'})
      self.assertEquals('crufty1', options.for_global_scope().global_crufty)
      self.assertWarning(w, 'global_crufty')

    with self.warnings_catcher() as w:
      options = self._parse('./pants', env={'PANTS_STALE_CRUFTY':'stale_and_crufty'})
      self.assertEquals('stale_and_crufty', options.for_scope('stale').crufty)
      self.assertWarning(w, 'crufty')

  def test_deprecated_options_config(self):
    with self.warnings_catcher() as w:
      options = self._parse('./pants', config={'GLOBAL':{'global_crufty':'crufty1'}})
      self.assertEquals('crufty1', options.for_global_scope().global_crufty)
      self.assertWarning(w, 'global_crufty')

    with self.warnings_catcher() as w:
      options = self._parse('./pants', config={'stale':{'crufty':'stale_and_crufty'}})
      self.assertEquals('stale_and_crufty', options.for_scope('stale').crufty)
      self.assertWarning(w, 'crufty')

  def test_mutually_exclusive_options_flags(self):
    """Ensure error is raised when mutual exclusive options are given together."""
    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants --mutex-foo=foo --mutex-bar=bar').for_global_scope()

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants --mutex-foo=foo --mutex-baz=baz').for_global_scope()

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants --mutex-bar=bar --mutex-baz=baz').for_global_scope()

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants --mutex-foo=foo --mutex-bar=bar --mutex-baz=baz').for_global_scope()

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants --new-name=foo --old-name=bar').for_global_scope()

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants stale --mutex-a=foo --mutex-b=bar').for_scope('stale')

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants stale --crufty-new=foo --crufty-old=bar').for_scope('stale')

    options = self._parse('./pants --mutex-foo=orz')
    self.assertEqual('orz', options.for_global_scope().mutex)

    options = self._parse('./pants --old-name=orz')
    self.assertEqual('orz', options.for_global_scope().new_name)

    options = self._parse('./pants stale --mutex-a=orz')
    self.assertEqual('orz', options.for_scope('stale').crufty_mutex)

    options = self._parse('./pants stale --crufty-old=orz')
    self.assertEqual('orz', options.for_scope('stale').crufty_new)

  def test_mutually_exclusive_options_mix(self):
    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants --mutex-foo=foo', env={'PANTS_MUTEX_BAR':'bar'}).for_global_scope()

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants --new-name=foo', env={'PANTS_OLD_NAME':'bar'}).for_global_scope()

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants --mutex-foo=foo', config={'GLOBAL':{'mutex_bar':'bar'}}).for_global_scope()

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants --new-name=foo', config={'GLOBAL':{'old_name':'bar'}}).for_global_scope()

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants stale --mutex-a=foo', env={'PANTS_STALE_MUTEX_B':'bar'}).for_scope('stale')

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants stale --crufty-new=foo', env={'PANTS_STALE_CRUFTY_OLD':'bar'}).for_scope('stale')

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants stale --mutex-a=foo', config={'stale':{'mutex_b':'bar'}}).for_scope('stale')

    with self.assertRaises(Parser.MutuallyExclusiveOptionError):
      self._parse('./pants stale --crufty-old=foo', config={'stale':{'crufty_new':'bar'}}).for_scope('stale')

    options = self._parse('./pants', env={'PANTS_OLD_NAME': 'bar'})
    self.assertEqual('bar', options.for_global_scope().new_name)

    options = self._parse('./pants', env={'PANTS_GLOBAL_MUTEX_BAZ': 'baz'})
    self.assertEqual('baz', options.for_global_scope().mutex)

    options = self._parse('./pants', env={'PANTS_STALE_MUTEX_B':'bar'})
    self.assertEqual('bar', options.for_scope('stale').crufty_mutex)

    options = self._parse('./pants', config={'stale':{'crufty_old':'bar'}})
    self.assertEqual('bar', options.for_scope('stale').crufty_new)

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
    self.assertEquals(99, options.for_scope('compile.java').a)

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
                          env={'PANTS_A': 100}, )
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    # Env has precedence over config.
    options = self._parse('./pants ',
                          config={
                            'DEFAULT': {'a': 100},
                          },
                          env={'PANTS_COMPILE_A': 99}, )
    self.assertEquals(100, options.for_global_scope().a)
    self.assertEquals(99, options.for_scope('compile').a)
    self.assertEquals(99, options.for_scope('compile.java').a)

    # Command line global overrides the middle scope setting in then env.
    options = self._parse('./pants --a=100',
                          env={'PANTS_COMPILE_A': 99}, )
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
                          env={'PANTS_A': 100}, )
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
    self.assertEquals((str, 'blah blah blah'), pairs[0])
    self.assertEquals((bool, True), pairs[1])
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
    _do_assert_fromfile(dest='listvalue', expected=['a', '1', '2'], contents=dedent("""
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

  def test_pants_global_designdoc_example(self):
    # The example from the design doc.
    # Get defaults from config and environment.
    config = {
      'GLOBAL': {'b': '99'},
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
      options.for_global_scope().c

    self.assertEqual(1, options.for_scope('compile').a)
    self.assertEqual(2, options.for_scope('compile').b)
    self.assertEqual(66, options.for_scope('compile').c)

    self.assertEqual(3, options.for_scope('compile.java').a)
    self.assertEqual(2, options.for_scope('compile.java').b)
    self.assertEqual(4, options.for_scope('compile.java').c)

  def test_pants_global_with_default(self):
    """
    This test makes sure values under [DEFAULT] still gets read.
    """
    config = {'DEFAULT': {'b': '99'},
              'GLOBAL': {'store_true_flag': True}
              }
    options = self._parse('./pants', config=config)

    self.assertEqual(99, options.for_global_scope().b)
    self.assertTrue(options.for_global_scope().store_true_flag)

  def test_double_registration(self):
    options = Options.create(env={},
                             config=self._create_config({}),
                             known_scope_infos=OptionsTest._known_scope_infos,
                             args=shlex.split('./pants'),
                             option_tracker=OptionTracker())
    options.register(GLOBAL_SCOPE, '--foo-bar')
    self.assertRaises(OptionAlreadyRegistered, lambda: options.register(GLOBAL_SCOPE, '--foo-bar'))

  def test_scope_deprecation(self):
    # Note: This test demonstrates that two different new scopes can deprecate the same
    # old scope. I.e., it's possible to split an old scope's options among multiple new scopes.
    class DummyOptionable1(Optionable):
      options_scope = 'new-scope1'
      options_scope_category = ScopeInfo.SUBSYSTEM
      deprecated_options_scope = 'deprecated-scope'
      deprecated_options_scope_removal_version = '9999.9.9.dev0'

    class DummyOptionable2(Optionable):
      options_scope = 'new-scope2'
      options_scope_category = ScopeInfo.SUBSYSTEM
      deprecated_options_scope = 'deprecated-scope'
      deprecated_options_scope_removal_version = '9999.9.9.dev0'

    options = Options.create(env={},
                             config=self._create_config({
                               'GLOBAL': {
                                 'inherited': 'aa'
                               },
                               DummyOptionable1.options_scope: {
                                 'foo': 'xx'
                               },
                               DummyOptionable1.deprecated_options_scope: {
                                 'foo': 'yy',
                                 'bar': 'zz',
                                 'baz': 'ww',
                                 'qux': 'uu'
                               },
                             }),
                             known_scope_infos=[
                               DummyOptionable1.get_scope_info(),
                               DummyOptionable2.get_scope_info()
                             ],
                             args=shlex.split('./pants --new-scope1-baz=vv'),
                             option_tracker=OptionTracker())

    options.register(GLOBAL_SCOPE, '--inherited')
    options.register(DummyOptionable1.options_scope, '--foo')
    options.register(DummyOptionable1.options_scope, '--bar')
    options.register(DummyOptionable1.options_scope, '--baz')
    options.register(DummyOptionable2.options_scope, '--qux')

    with self.warnings_catcher() as w:
      vals1 = options.for_scope(DummyOptionable1.options_scope)

    # Check that we got a warning, but not for the inherited option.
    self.assertEquals(1, len(w))
    self.assertTrue(isinstance(w[0].message, DeprecationWarning))
    self.assertNotIn('inherited', w[0].message)

    # Check values.
    # Deprecated scope takes precedence at equal rank.
    self.assertEquals('yy', vals1.foo)
    self.assertEquals('zz', vals1.bar)
    # New scope takes precedence at higher rank.
    self.assertEquals('vv', vals1.baz)

    with self.warnings_catcher() as w:
      vals2 = options.for_scope(DummyOptionable2.options_scope)

    # Check that we got a warning.
    self.assertEquals(1, len(w))
    self.assertTrue(isinstance(w[0].message, DeprecationWarning))
    self.assertNotIn('inherited', w[0].message)

    # Check values.
    self.assertEquals('uu', vals2.qux)

  def test_scope_deprecation_defaults(self):
    # Confirms that a DEFAULT option does not trigger deprecation warnings for a deprecated scope.
    class DummyOptionable1(Optionable):
      options_scope = 'new-scope1'
      options_scope_category = ScopeInfo.SUBSYSTEM
      deprecated_options_scope = 'deprecated-scope'
      deprecated_options_scope_removal_version = '9999.9.9.dev0'

    options = Options.create(env={},
                             config=self._create_config({
                               'DEFAULT': {
                                 'foo': 'aa'
                               },
                               DummyOptionable1.options_scope: {
                                 'foo': 'xx'
                               },
                             }),
                             known_scope_infos=[
                               DummyOptionable1.get_scope_info(),
                             ],
                             args=shlex.split('./pants'),
                             option_tracker=OptionTracker())

    options.register(DummyOptionable1.options_scope, '--foo')

    with self.warnings_catcher() as w:
      vals1 = options.for_scope(DummyOptionable1.options_scope)

    # Check that we got no warnings and that the actual scope took precedence.
    self.assertEquals(0, len(w))
    self.assertEquals('xx', vals1.foo)
