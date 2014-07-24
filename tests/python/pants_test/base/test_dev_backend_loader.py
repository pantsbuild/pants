# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import uuid
import sys
import types

import unittest2

from pants.base.build_configuration import BuildConfiguration
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.dev_backend_loader import load_backend
from pants.base.exceptions import BuildConfigurationError
from pants.base.target import Target
from pants.goal.goal import Goal
from pants.goal.phase import Phase


class LoaderTest(unittest2.TestCase):
  def setUp(self):
    self.build_configuration = BuildConfiguration()

  def tearDown(self):
    Phase.clear()

  @contextmanager
  def create_register(self, build_file_aliases=None, register_commands=None, register_goals=None,
                      module_name='register'):

    package_name = b'__test_package_{0}'.format(uuid.uuid4().hex)
    self.assertFalse(package_name in sys.modules)

    package_module = types.ModuleType(package_name)
    sys.modules[package_name] = package_module
    try:
      register_module_fqn = b'{0}.{1}'.format(package_name, module_name)
      register_module = types.ModuleType(register_module_fqn)
      setattr(package_module, module_name, register_module)
      sys.modules[register_module_fqn] = register_module

      def register_entrypoint(function_name, function):
        if function:
          setattr(register_module, function_name, function)

      register_entrypoint('build_file_aliases', build_file_aliases)
      register_entrypoint('register_commands', register_commands)
      register_entrypoint('register_goals', register_goals)

      yield package_name
    finally:
      del sys.modules[package_name]

  def assert_empty_aliases(self):
    registered_aliases = self.build_configuration.registered_aliases()
    self.assertEqual(0, len(registered_aliases.targets))
    self.assertEqual(0, len(registered_aliases.objects))
    self.assertEqual(0, len(registered_aliases.context_aware_object_factories))

  def test_load_valid_empty(self):
    with self.create_register() as backend_package:
      load_backend(self.build_configuration, backend_package)
      self.assert_empty_aliases()

  def test_load_valid_partial_aliases(self):
    aliases = BuildFileAliases.create(targets={'bob': Target},
                                      objects={'MEANING_OF_LIFE': 42})
    with self.create_register(build_file_aliases=lambda: aliases) as backend_package:
      load_backend(self.build_configuration, backend_package)
      registered_aliases = self.build_configuration.registered_aliases()
      self.assertEqual(Target, registered_aliases.targets['bob'])
      self.assertEqual(42, registered_aliases.objects['MEANING_OF_LIFE'])

  def test_load_valid_partial_goals(self):
    def register_goals():
      Phase('jack').install(Goal('jill', lambda: 42))

    with self.create_register(register_goals=register_goals) as backend_package:
      Phase.clear()
      self.assertEqual(0, len(Phase.all()))

      load_backend(self.build_configuration, backend_package)
      self.assert_empty_aliases()
      self.assertEqual(1, len(Phase.all()))

      goals = Phase('jack').goals()
      self.assertEqual(1, len(goals))

      goal = goals[0]
      self.assertEqual('jill', goal.name)

  def test_load_invalid_entrypoint(self):
    def build_file_aliases(bad_arg):
      return BuildFileAliases.create()

    with self.create_register(build_file_aliases=build_file_aliases) as backend_package:
      with self.assertRaises(BuildConfigurationError):
        load_backend(self.build_configuration, backend_package)

  def test_load_invalid_module(self):
    with self.create_register(module_name='register2') as backend_package:
      with self.assertRaises(BuildConfigurationError):
        load_backend(self.build_configuration, backend_package)
