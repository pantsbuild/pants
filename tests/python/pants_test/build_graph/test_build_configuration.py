# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager

from pants.base.build_file import BuildFile
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.target import Target
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import touch


class BuildConfigurationTest(unittest.TestCase):
  def setUp(self):
    self.build_configuration = BuildConfiguration()

  def _register_aliases(self, **kwargs):
    self.build_configuration.register_aliases(BuildFileAliases(**kwargs))

  def test_register_bad(self):
    with self.assertRaises(TypeError):
      self.build_configuration.register_aliases(42)

  def test_register_target_alias(self):
    class Fred(Target):
      pass

    self._register_aliases(targets={'fred': Fred})
    aliases = self.build_configuration.registered_aliases()
    self.assertEqual({}, aliases.target_macro_factories)
    self.assertEqual({}, aliases.objects)
    self.assertEqual({}, aliases.context_aware_object_factories)
    self.assertEqual(dict(fred=Fred), aliases.target_types)

    with self._create_mock_build_file('fred') as build_file:
      parse_state = self.build_configuration.initialize_parse_state(build_file)

      self.assertEqual(0, len(parse_state.registered_addressable_instances))
      self.assertEqual(1, len(parse_state.parse_globals))

      target_call_proxy = parse_state.parse_globals['fred']
      target_call_proxy(name='jake')

      self.assertEqual(1, len(parse_state.registered_addressable_instances))
      name, target_proxy = parse_state.registered_addressable_instances.pop()
      self.assertEqual('jake', target_proxy.addressed_name)
      self.assertEqual(Fred, target_proxy.addressed_type)

  def test_register_target_macro_facory(self):
    class Fred(Target):
      pass

    class FredMacro(TargetMacro):
      def __init__(self, parse_context):
        self._parse_context = parse_context

      def expand(self, *args, **kwargs):
        return self._parse_context.create_object(Fred, name='frog', dependencies=[kwargs['name']])

    class FredFactory(TargetMacro.Factory):
      @property
      def target_types(self):
        return {Fred}

      def macro(self, parse_context):
        return FredMacro(parse_context)

    factory = FredFactory()

    self._register_aliases(targets={'fred': factory})
    aliases = self.build_configuration.registered_aliases()
    self.assertEqual({}, aliases.target_types)
    self.assertEqual({}, aliases.objects)
    self.assertEqual({}, aliases.context_aware_object_factories)
    self.assertEqual(dict(fred=factory), aliases.target_macro_factories)

    with self._create_mock_build_file('fred') as build_file:
      parse_state = self.build_configuration.initialize_parse_state(build_file)

      self.assertEqual(0, len(parse_state.registered_addressable_instances))
      self.assertEqual(1, len(parse_state.parse_globals))

      target_call_proxy = parse_state.parse_globals['fred']
      target_call_proxy(name='jake')

      self.assertEqual(1, len(parse_state.registered_addressable_instances))
      name, target_proxy = parse_state.registered_addressable_instances.pop()
      self.assertEqual('frog', target_proxy.addressed_name)
      self.assertEqual(Fred, target_proxy.addressed_type)
      self.assertEqual(['jake'], target_proxy.dependency_specs)

  def test_register_exposed_object(self):
    self._register_aliases(objects={'jane': 42})

    aliases = self.build_configuration.registered_aliases()
    self.assertEqual({}, aliases.target_types)
    self.assertEqual({}, aliases.target_macro_factories)
    self.assertEqual({}, aliases.context_aware_object_factories)
    self.assertEqual(dict(jane=42), aliases.objects)

    with self._create_mock_build_file('jane') as build_file:
      parse_state = self.build_configuration.initialize_parse_state(build_file)

      self.assertEqual(0, len(parse_state.registered_addressable_instances))
      self.assertEqual(1, len(parse_state.parse_globals))
      self.assertEqual(42, parse_state.parse_globals['jane'])

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
    self._register_aliases(context_aware_object_factories={'george': context_aware_object_factory})

    aliases = self.build_configuration.registered_aliases()
    self.assertEqual({}, aliases.target_types)
    self.assertEqual({}, aliases.target_macro_factories)
    self.assertEqual({}, aliases.objects)
    self.assertEqual(dict(george=context_aware_object_factory),
                     aliases.context_aware_object_factories)

    with temporary_dir() as root:
      build_file_path = os.path.join(root, 'george', 'BUILD')
      touch(build_file_path)
      build_file = BuildFile(FileSystemProjectTree(root), 'george/BUILD')
      parse_state = self.build_configuration.initialize_parse_state(build_file)

      self.assertEqual(0, len(parse_state.registered_addressable_instances))
      self.assertEqual(1, len(parse_state.parse_globals))
      yield parse_state.parse_globals['george']

  @contextmanager
  def _create_mock_build_file(self, dirname):
    with temporary_dir() as root:
      os.mkdir(os.path.join(root, dirname))
      touch(os.path.join(root, dirname, 'BUILD'))
      yield BuildFile(FileSystemProjectTree(root), os.path.join(dirname, 'BUILD'))
