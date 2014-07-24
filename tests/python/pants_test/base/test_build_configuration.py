# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import os
import unittest2

from pants.base.address import SyntheticAddress
from pants.base.build_configuration import BuildConfiguration
from pants.base.build_file import BuildFile
from pants.base.build_graph import BuildGraph
from pants.base.target import Target
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import touch


class BuildConfigurationTest(unittest2.TestCase):
  def setUp(self):
    self.build_configuration = BuildConfiguration()

  def test_register_target_alias(self):
    class Fred(Target):
      pass

    self.build_configuration.register_target_alias('fred', Fred)
    aliases = self.build_configuration.registered_aliases()
    self.assertEqual({}, aliases.objects)
    self.assertEqual({}, aliases.context_aware_object_factories)
    self.assertEqual(dict(fred=Fred), aliases.targets)

    build_file = BuildFile('/tmp', 'fred', must_exist=False)
    parse_state = self.build_configuration.initialize_parse_state(build_file)

    self.assertEqual(0, len(parse_state.registered_target_proxies))

    self.assertEqual(2, len(parse_state.parse_globals))

    self.assertEqual(parse_state.parse_globals['__file__'],
                     os.path.realpath('/tmp/fred'))

    target_call_proxy = parse_state.parse_globals['fred']
    target_call_proxy(name='jake')
    self.assertEqual(1, len(parse_state.registered_target_proxies))
    target_proxy = parse_state.registered_target_proxies.pop()
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
    self.assertEqual({}, aliases.context_aware_object_factories)
    self.assertEqual(dict(jane=42), aliases.objects)

    build_file = BuildFile('/tmp', 'jane', must_exist=False)
    parse_state = self.build_configuration.initialize_parse_state(build_file)

    self.assertEqual(0, len(parse_state.registered_target_proxies))

    self.assertEqual(2, len(parse_state.parse_globals))
    self.assertEqual(parse_state.parse_globals['__file__'],
                     os.path.realpath('/tmp/jane'))
    self.assertEqual(42, parse_state.parse_globals['jane'])

  def test_register_bad_exposed_object(self):
    with self.assertRaises(TypeError):
      self.build_configuration.register_exposed_object('jane', Target)

  def test_register_exposed_context_aware_function(self):
    self.do_test_exposed_context_aware_function(lambda context: lambda: context.rel_path)
    self.do_test_exposed_context_aware_function(lambda context=None: lambda: context.rel_path)

  def george_method(self, parse_context):
    return lambda: parse_context.rel_path

  def test_register_exposed_context_aware_method(self):
    self.do_test_exposed_context_aware_function(self.george_method)

  @classmethod
  def george_classmethod(cls, parse_context):
    return lambda: parse_context.rel_path

  def test_register_exposed_context_aware_classmethod(self):
    self.do_test_exposed_context_aware_function(self.george_classmethod)

  @staticmethod
  def george_staticmethod(parse_context):
    return lambda: parse_context.rel_path

  def test_register_exposed_context_aware_staticmethod(self):
    self.do_test_exposed_context_aware_function(self.george_staticmethod)

  def do_test_exposed_context_aware_function(self, func, *args, **kwargs):
    with self.do_test_exposed_context_aware_object(func) as context_aware_object:
      self.assertEqual('george', context_aware_object(*args, **kwargs))

  def test_register_exposed_context_aware_class(self):
    class George(object):
      def __init__(self, parse_context):
        self._parse_context = parse_context

      def honorific(self):
        return len(self._parse_context.rel_path)

    with self.do_test_exposed_context_aware_object(George) as context_aware_object:
      self.assertEqual(6, context_aware_object.honorific())

  @contextmanager
  def do_test_exposed_context_aware_object(self, context_aware_object_factory):
    self.build_configuration.register_exposed_context_aware_object_factory(
        'george', context_aware_object_factory)

    aliases = self.build_configuration.registered_aliases()
    self.assertEqual({}, aliases.targets)
    self.assertEqual({}, aliases.objects)
    self.assertEqual(dict(george=context_aware_object_factory),
                     aliases.context_aware_object_factories)

    with temporary_dir() as root:
      build_file_path = os.path.join(root, 'george', 'BUILD')
      touch(build_file_path)
      build_file = BuildFile(root, 'george')
      parse_state = self.build_configuration.initialize_parse_state(build_file)

      self.assertEqual(0, len(parse_state.registered_target_proxies))

      self.assertEqual(2, len(parse_state.parse_globals))
      self.assertEqual(os.path.realpath(build_file_path),
                       parse_state.parse_globals['__file__'])
      yield parse_state.parse_globals['george']

  def test_register_bad_exposed_context_aware_object(self):
    with self.assertRaises(TypeError):
      self.build_configuration.register_exposed_context_aware_object_factory('george', 1)
