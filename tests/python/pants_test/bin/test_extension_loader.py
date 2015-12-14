# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
import types
import unittest
import uuid
from contextlib import contextmanager

from pkg_resources import (Distribution, EmptyProvider, VersionConflict, WorkingSet, working_set,
                           yield_lines)

from pants.base.exceptions import BuildConfigurationError
from pants.bin.extension_loader import (PluginLoadOrderError, PluginNotFound, load_backend,
                                        load_plugins)
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar
from pants.subsystem.subsystem import Subsystem
from pants.task.task import Task


class MockMetadata(EmptyProvider):

  def __init__(self, metadata):
    self.metadata = metadata

  def has_metadata(self, name):
    return name in self.metadata

  def get_metadata(self, name):
    return self.metadata[name]

  def get_metadata_lines(self, name):
    return yield_lines(self.get_metadata(name))


class DummySubsystem1(Subsystem):
  options_scope = 'dummy-subsystem1'


class DummySubsystem2(Subsystem):
  options_scope = 'dummy-subsystem2'


class DummyTarget(Target):

  @classmethod
  def subsystems(cls):
    return (DummySubsystem1,)


class DummyObject1(object):
  # Test that registering an object with no subsystems() method succeeds.
  pass


class DummyObject2(object):

  @classmethod
  def subsystems(cls):
    return (DummySubsystem2,)


class DummyTask(Task):

  def execute(self): return 42


class LoaderTest(unittest.TestCase):

  def setUp(self):
    self.build_configuration = BuildConfiguration()
    self.working_set = WorkingSet()
    for entry in working_set.entries:
      self.working_set.add_entry(entry)

  def tearDown(self):
    Goal.clear()

  @contextmanager
  def create_register(self, build_file_aliases=None, register_goals=None, global_subsystems=None,
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
      register_entrypoint('global_subsystems', global_subsystems)
      register_entrypoint('register_goals', register_goals)

      yield package_name
    finally:
      del sys.modules[package_name]

  def assert_empty_aliases(self):
    registered_aliases = self.build_configuration.registered_aliases()
    self.assertEqual(0, len(registered_aliases.target_types))
    self.assertEqual(0, len(registered_aliases.target_macro_factories))
    self.assertEqual(0, len(registered_aliases.objects))
    self.assertEqual(0, len(registered_aliases.context_aware_object_factories))
    self.assertEqual(self.build_configuration.subsystems(), set())

  def test_load_valid_empty(self):
    with self.create_register() as backend_package:
      load_backend(self.build_configuration, backend_package)
      self.assert_empty_aliases()

  def test_load_valid_partial_aliases(self):
    aliases = BuildFileAliases(targets={'bob': DummyTarget},
                               objects={'obj1': DummyObject1,
                                        'obj2': DummyObject2})
    with self.create_register(build_file_aliases=lambda: aliases) as backend_package:
      load_backend(self.build_configuration, backend_package)
      registered_aliases = self.build_configuration.registered_aliases()
      self.assertEqual(DummyTarget, registered_aliases.target_types['bob'])
      self.assertEqual(DummyObject1, registered_aliases.objects['obj1'])
      self.assertEqual(DummyObject2, registered_aliases.objects['obj2'])
      self.assertEqual(self.build_configuration.subsystems(), {DummySubsystem1, DummySubsystem2})

  def test_load_valid_partial_goals(self):
    def register_goals():
      Goal.by_name('jack').install(TaskRegistrar('jill', DummyTask))

    with self.create_register(register_goals=register_goals) as backend_package:
      Goal.clear()
      self.assertEqual(0, len(Goal.all()))

      load_backend(self.build_configuration, backend_package)
      self.assert_empty_aliases()
      self.assertEqual(1, len(Goal.all()))

      task_names = Goal.by_name('jack').ordered_task_names()
      self.assertEqual(1, len(task_names))

      task_name = task_names[0]
      self.assertEqual('jill', task_name)

  def test_load_invalid_entrypoint(self):
    def build_file_aliases(bad_arg):
      return BuildFileAliases()

    with self.create_register(build_file_aliases=build_file_aliases) as backend_package:
      with self.assertRaises(BuildConfigurationError):
        load_backend(self.build_configuration, backend_package)

  def test_load_invalid_module(self):
    with self.create_register(module_name='register2') as backend_package:
      with self.assertRaises(BuildConfigurationError):
        load_backend(self.build_configuration, backend_package)

  def test_load_missing_plugin(self):
    with self.assertRaises(PluginNotFound):
      self.load_plugins(['Foobar'])

  def get_mock_plugin(self, name, version, reg=None, alias=None, after=None):
    """Make a fake Distribution (optionally with entry points)

    Note the entry points do not actually point to code in the returned distribution --
    the distribution does not even have a location and does not contain any code, just metadata.

    A module is synthesized on the fly and installed into sys.modules under a random name.
    If optional entry point callables are provided, those are added as methods to the module and
    their name (foo/bar/baz in fake module) is added as the requested entry point to the mocked
    metadata added to the returned dist.

    :param string name: project_name for distribution (see pkg_resources)
    :param string version: version for distribution (see pkg_resources)
    :param callable reg: Optional callable for goal registration entry point
    :param callable alias: Optional callable for build_file_aliases entry point
    :param callable after: Optional callable for load_after list entry point
    """

    plugin_pkg = b'demoplugin{0}'.format(uuid.uuid4().hex)
    pkg = types.ModuleType(plugin_pkg)
    sys.modules[plugin_pkg] = pkg
    module_name = b'{0}.{1}'.format(plugin_pkg, 'demo')
    plugin = types.ModuleType(module_name)
    setattr(pkg, 'demo', plugin)
    sys.modules[module_name] = plugin

    metadata = {}
    entry_lines = []

    if reg is not None:
      setattr(plugin, 'foo', reg)
      entry_lines.append('register_goals = {}:foo\n'.format(module_name))

    if alias is not None:
      setattr(plugin, 'bar', alias)
      entry_lines.append('build_file_aliases = {}:bar\n'.format(module_name))

    if after is not None:
      setattr(plugin, 'baz', after)
      entry_lines.append('load_after = {}:baz\n'.format(module_name))

    if entry_lines:
      entry_data = '[pantsbuild.plugin]\n{}\n'.format('\n'.join(entry_lines))
      metadata = {'entry_points.txt': entry_data}

    return Distribution(project_name=name, version=version, metadata=MockMetadata(metadata))

  def load_plugins(self, plugins):
    load_plugins(self.build_configuration, plugins, self.working_set)

  def test_plugin_load_and_order(self):
    d1 = self.get_mock_plugin('demo1', '0.0.1', after=lambda: ['demo2'])
    d2 = self.get_mock_plugin('demo2', '0.0.3')
    self.working_set.add(d1)

    # Attempting to load 'demo1' then 'demo2' should fail as 'demo1' requires 'after'=['demo2'].
    with self.assertRaises(PluginLoadOrderError):
      self.load_plugins(['demo1', 'demo2'])

    # Attempting to load 'demo2' first should fail as it is not (yet) installed.
    with self.assertRaises(PluginNotFound):
      self.load_plugins(['demo2', 'demo1'])

    # Installing demo2 and then loading in correct order should work though.
    self.working_set.add(d2)
    self.load_plugins(['demo2>=0.0.2', 'demo1'])

    # But asking for a bad (not installed) version fails.
    with self.assertRaises(VersionConflict):
      self.load_plugins(['demo2>=0.0.5'])

  def test_plugin_installs_goal(self):
    def reg_goal():
      Goal.by_name('plugindemo').install(TaskRegistrar('foo', DummyTask))
    self.working_set.add(self.get_mock_plugin('regdemo', '0.0.1', reg=reg_goal))

    # Start without the custom goal.
    self.assertEqual(0, len(Goal.by_name('plugindemo').ordered_task_names()))

    # Load plugin which registers custom goal.
    self.load_plugins(['regdemo'])

    # Now the custom goal exists.
    self.assertEqual(1, len(Goal.by_name('plugindemo').ordered_task_names()))
    self.assertEqual('foo', Goal.by_name('plugindemo').ordered_task_names()[0])

  def test_plugin_installs_alias(self):
    def reg_alias():
      return BuildFileAliases(targets={'pluginalias': DummyTarget},
                              objects={'FROMPLUGIN1': DummyObject1,
                                       'FROMPLUGIN2': DummyObject2})
    self.working_set.add(self.get_mock_plugin('aliasdemo', '0.0.1', alias=reg_alias))

    # Start with no aliases.
    self.assert_empty_aliases()

    # Now load the plugin which defines aliases.
    self.load_plugins(['aliasdemo'])

    # Aliases now exist.
    registered_aliases = self.build_configuration.registered_aliases()
    self.assertEqual(DummyTarget, registered_aliases.target_types['pluginalias'])
    self.assertEqual(DummyObject1, registered_aliases.objects['FROMPLUGIN1'])
    self.assertEqual(DummyObject2, registered_aliases.objects['FROMPLUGIN2'])
    self.assertEqual(self.build_configuration.subsystems(), {DummySubsystem1, DummySubsystem2})

  def test_subsystems(self):
    def global_subsystems():
      return {DummySubsystem1, DummySubsystem2}
    with self.create_register(global_subsystems=global_subsystems) as backend_package:
      load_backend(self.build_configuration, backend_package)
      self.assertEqual(self.build_configuration.subsystems(),
                       {DummySubsystem1, DummySubsystem2})
