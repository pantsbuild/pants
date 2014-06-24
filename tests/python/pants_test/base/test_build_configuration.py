# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import os

import unittest2
from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import touch

from pants.base.address import SyntheticAddress
from pants.base.build_configuration import BuildConfiguration
from pants.base.build_file import BuildFile
from pants.base.build_graph import BuildGraph
from pants.base.target import Target


class BuildConfigurationTest(unittest2.TestCase):
  def setUp(self):
    self.build_configuration = BuildConfiguration()

  def test_register_target_alias(self):
    class Fred(Target):
      pass

    self.build_configuration.register_target_alias('fred', Fred)
    aliases = self.build_configuration.registered_aliases()
    self.assertEqual({}, aliases.objects)
    self.assertEqual({}, aliases.macros)
    self.assertEqual(dict(fred=Fred), aliases.targets)

    build_file = BuildFile('/tmp', 'fred', must_exist=False)
    parse_context = self.build_configuration.create_parse_context(build_file)

    self.assertEqual(0, len(parse_context.registered_target_proxies))

    self.assertEqual(2, len(parse_context.parse_globals))

    self.assertEqual('/tmp/fred', parse_context.parse_globals['__file__'])

    target_call_proxy = parse_context.parse_globals['fred']
    target_call_proxy(name='jake')
    self.assertEqual(1, len(parse_context.registered_target_proxies))
    target_proxy = parse_context.registered_target_proxies.pop()
    self.assertEqual('jake', target_proxy.name)
    self.assertEqual(Fred, target_proxy.target_type)
    self.assertEqual(build_file, target_proxy.build_file)

  def test_register_bad_target_alias(self):
    with self.assertRaises(TypeError):
      self.build_configuration.register_target_alias('fred', object())

    target = Target('fred', SyntheticAddress.parse('a:b'), BuildGraph())
    with self.assertRaises(TypeError):
      self.build_configuration.register_target_alias('fred', target)

  def test_register_exposed_object(self):
    self.build_configuration.register_exposed_object('jane', 42)

    aliases = self.build_configuration.registered_aliases()
    self.assertEqual({}, aliases.targets)
    self.assertEqual({}, aliases.macros)
    self.assertEqual(dict(jane=42), aliases.objects)

    build_file = BuildFile('/tmp', 'jane', must_exist=False)
    parse_context = self.build_configuration.create_parse_context(build_file)

    self.assertEqual(0, len(parse_context.registered_target_proxies))

    self.assertEqual(2, len(parse_context.parse_globals))
    self.assertEqual('/tmp/jane', parse_context.parse_globals['__file__'])
    self.assertEqual(42, parse_context.parse_globals['jane'])

  def test_register_bad_exposed_object(self):
    with self.assertRaises(TypeError):
      self.build_configuration.register_exposed_object('jane', Target)

  def test_register_exposed_macro_function(self):
    self.do_test_exposed_macro_func(lambda macro_context: macro_context.rel_path)
    self.do_test_exposed_macro_func(lambda macro_context=None: macro_context.rel_path)
    self.do_test_exposed_macro_func(lambda a, b, macro_context: macro_context.rel_path, 'a', 'b')
    self.do_test_exposed_macro_func(lambda a, macro_context, b=None: macro_context.rel_path, 'a')
    self.do_test_exposed_macro_func(lambda a, **kwargs: kwargs['macro_context'].rel_path, 'a')

  def george_method(self, macro_context):
    return macro_context.rel_path

  def test_register_exposed_macro_method(self):
    self.do_test_exposed_macro_func(self.george_method)

  @classmethod
  def george_classmethod(cls, macro_context):
    return macro_context.rel_path

  def test_register_exposed_macro_classmethod(self):
    self.do_test_exposed_macro_func(self.george_classmethod)

  @staticmethod
  def george_staticmethod(macro_context):
    return macro_context.rel_path

  def test_register_exposed_macro_staticmethod(self):
    self.do_test_exposed_macro_func(self.george_staticmethod)

  def do_test_exposed_macro_func(self, func, *args, **kwargs):
    with self.do_test_exposed_macro(func) as macro:
      self.assertEqual('george', macro(*args, **kwargs))

  def test_register_exposed_macro_class(self):
    class George(object):
      def __init__(self, macro_context):
        self._macro_context = macro_context

      def honorific(self):
        return len(self._macro_context.rel_path)

    with self.do_test_exposed_macro(George) as macro:
      self.assertEqual(6, macro.honorific())

  @contextmanager
  def do_test_exposed_macro(self, macro):
    self.build_configuration.register_exposed_macro('george', macro)

    aliases = self.build_configuration.registered_aliases()
    self.assertEqual({}, aliases.targets)
    self.assertEqual({}, aliases.objects)
    self.assertEqual(dict(george=macro), aliases.macros)

    with temporary_dir() as root:
      build_file_path = os.path.join(root, 'george', 'BUILD')
      touch(build_file_path)
      build_file = BuildFile(root, 'george')
      parse_context = self.build_configuration.create_parse_context(build_file)

      self.assertEqual(0, len(parse_context.registered_target_proxies))

      self.assertEqual(2, len(parse_context.parse_globals))
      self.assertEqual(build_file_path, parse_context.parse_globals['__file__'])
      yield parse_context.parse_globals['george']

  def test_register_bad_exposed_macro(self):
    with self.assertRaises(TypeError):
      self.build_configuration.register_exposed_macro('george', 1)

    with self.assertRaises(TypeError):
      self.build_configuration.register_exposed_macro('george', tuple)

    with self.assertRaises(TypeError):
      self.build_configuration.register_exposed_macro('george', lambda ace: 42)

    with self.assertRaises(TypeError):
      self.build_configuration.register_exposed_macro('george', lambda macro_context, ace: 42)

    class George(object):
      pass

    with self.assertRaises(TypeError):
      self.build_configuration.register_exposed_macro('george', George)

    class GeorgeII(object):
      def __init__(self, ace):
        pass

    with self.assertRaises(TypeError):
      self.build_configuration.register_exposed_macro('george', GeorgeII)

    class GeorgeIII(object):
      def __init__(self, macro_context, ace):
        pass

    with self.assertRaises(TypeError):
      self.build_configuration.register_exposed_macro('george', GeorgeIII)
