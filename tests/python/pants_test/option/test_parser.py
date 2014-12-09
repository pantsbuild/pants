# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)
import argparse

from textwrap import dedent
import unittest2 as unittest

from pants.option.errors import ParseError
from pants.option.option_value_container import OptionValueContainer
from pants.option.parser import Parser
from pants_test.base.context_utils import create_config


class ParserTest(unittest.TestCase):
  @classmethod
  def create_parser(cls, scope='', env=None, config='', parent_parser=None):
    return Parser(env=env or {}, config=create_config(sample_ini=config), scope=scope,
                  parent_parser=parent_parser)

  def test_config_only_help(self):
    parser = self.create_parser()
    parser.register('foo', config_only=True)
    found = False
    help_text = parser.format_help()
    for line in help_text.splitlines():
      if line.strip().startswith('[foo]'):
        found = True
    self.assertTrue(found, "Expected to find help text for the 'foo' config-only option "
                           "presented as '[foo]', got:\n{0}".format(help_text))

  def test_config_only_none(self):
    parser = self.create_parser()
    parser.register('foo', config_only=True)
    parser.register('bar', config_only=True, type=bool)

    parsed = parser.parse_args(args=[], namespace=OptionValueContainer())
    self.assertIsNone(parsed.foo)
    self.assertFalse(parsed.bar)

  def test_config_only_defaults(self):
    parser = self.create_parser('test.scope')
    parser.register('foo', config_only=True, type=int, default=42)

    parsed = parser.parse_args(args=[], namespace=OptionValueContainer())
    self.assertEqual(42, parsed.foo)

  def test_config_only_config(self):
    parser = self.create_parser('test.scope',
                                config=dedent('''
                                [not.relevant.scope]
                                foo: False
                                [test.scope]
                                foo: True
                                bar: True
                                [DEFAULT]
                                baz: 42
                                '''))
    parser.register('foo', config_only=True, type=bool)
    parser.register('bar', config_only=True)
    parser.register('baz', config_only=True, type=int)

    parsed = parser.parse_args(args=[], namespace=OptionValueContainer())
    self.assertEqual(True, parsed.foo)
    self.assertEqual('True', parsed.bar)
    self.assertEqual(42, parsed.baz)

  def test_config_only_choices(self):
    parser = self.create_parser('test.scope',
                                env=dict(PANTS_TEST_SCOPE_BAZ='jake'),
                                config=dedent('''
                                [test.scope]
                                foo: 2
                                bar: 42
                                '''))

    with self.assertRaises(parser.InvalidConfigValueError):
      parser.register('bar', config_only=True, type=int, choices=[4, 5, 6])
    with self.assertRaises(parser.InvalidConfigValueError):
      parser.register('bar', config_only=True, choices=[42])  # type mismatch, this defaults as str
    with self.assertRaises(parser.InvalidConfigValueError):
      parser.register('baz', config_only=True, choices=['jane', 'jill'])

    parser.register('foo', config_only=True, type=int, choices=[1, 2, 3])
    parser.register('bar', config_only=True, type=int, choices=[42])
    parser.register('baz', config_only=True, choices=['george', 'jake'])

    parsed = parser.parse_args(args=[], namespace=OptionValueContainer())
    self.assertEqual(2, parsed.foo)
    self.assertEqual(42, parsed.bar)
    self.assertEqual('jake', parsed.baz)

  def test_config_only_env(self):
    parser = self.create_parser('test.scope',
                                env=dict(PANTS_TEST_SCOPE_NONE='env_value_none',
                                         PANTS_TEST_SCOPE_DEFAULT='env_value_default',
                                         PANTS_TEST_SCOPE_CONFIG='env_value_config',
                                         PANTS_TEST_SCOPE_ENV='env_value'),
                                config=dedent('''
                                [test.scope]
                                config: config_value
                                '''))
    parser.register('none', config_only=True)
    parser.register('default', config_only=True, default='default_value')
    parser.register('config', config_only=True)
    parser.register('env', config_only=True)

    parsed = parser.parse_args(args=[], namespace=OptionValueContainer())
    self.assertEqual('env_value_none', parsed.none)
    self.assertEqual('env_value_default', parsed.default)
    self.assertEqual('env_value_config', parsed.config)
    self.assertEqual('env_value', parsed.env)

  def test_config_only_no_flag(self):
    parser = self.create_parser()
    parser.register('foo', config_only=True)

    with self.assertRaises(ParseError):
      parser.parse_args(args=['--foo'], namespace=OptionValueContainer())

  def test_config_only_names(self):
    parser = self.create_parser()

    # Check that flag-like names cannot be used.
    with self.assertRaises(parser.InvalidOptionNameError):
      parser.register('-f', config_only=True)
    with self.assertRaises(parser.InvalidOptionNameError):
      parser.register('--foo', config_only=True)

    # Check that ini-file section header-like names cannot be used.
    with self.assertRaises(parser.InvalidOptionNameError):
      parser.register('[foo', config_only=True)
    with self.assertRaises(parser.InvalidOptionNameError):
      parser.register('foo]', config_only=True)
    with self.assertRaises(parser.InvalidOptionNameError):
      parser.register('f[o]o', config_only=True)
    with self.assertRaises(parser.InvalidOptionNameError):
      parser.register('[foo]', config_only=True)

    # Check that only valid shell identifiers can be used (for env var support).
    with self.assertRaises(parser.InvalidOptionNameError):
      parser.register('1', config_only=True)
    with self.assertRaises(parser.InvalidOptionNameError):
      parser.register('$', config_only=True)

    # Check that a single name is required.
    with self.assertRaises(parser.InvalidOptionNameError):
      parser.register(config_only=True)
    with self.assertRaises(parser.InvalidOptionNameError):
      parser.register('foo', 'bar', config_only=True)
    with self.assertRaises(parser.InvalidOptionNameError):
      parser.register('foo', '-f', config_only=True)

  def test_config_only_no_action(self):
    parser = self.create_parser()
    parser.register('foo', config_only=True, action=None)

    class TestAction(argparse.Action):
      def __call__(me, parser, namespace, values, option_string=None):
        self.fail('Should never be called')

    with self.assertRaises(parser.UnsupportedOptionError):
      parser.register('bar', config_only=True, action=TestAction)

  def test_config_only_no_const(self):
    parser = self.create_parser()
    parser.register('foo', config_only=True, const=None)

    with self.assertRaises(parser.UnsupportedOptionError):
      parser.register('foo', config_only=True, const='bar')
