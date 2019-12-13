# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
import types
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from pkg_resources import (
  Distribution,
  EmptyProvider,
  VersionConflict,
  WorkingSet,
  working_set,
  yield_lines,
)

from pants.base.exceptions import BuildConfigurationError
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants.engine.rules import RootRule, rule
from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar
from pants.init.extension_loader import (
  PluginLoadOrderError,
  PluginNotFound,
  load_backend,
  load_backends_and_plugins,
  load_plugins,
)
from pants.subsystem.subsystem import Subsystem
from pants.task.task import Task


class MockMetadata(EmptyProvider):

  def __init__(self, metadata):
    super().__init__()
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


class DummyTarget2(Target):

  @classmethod
  def subsystems(cls):
    return (DummySubsystem2,)


class DummyObject1(object):
  # Test that registering an object with no subsystems() method succeeds.
  pass


class DummyObject2(object):

  @classmethod
  def subsystems(cls):
    return (DummySubsystem2,)


class DummyTask(Task):

  def execute(self): return 42


@dataclass(frozen=True)
class RootType:
  value: Any


@dataclass(frozen=True)
class WrapperType:
  value: Any


@rule
def example_rule(root_type: RootType) -> WrapperType:
  return WrapperType(root_type.value)


class PluginProduct:
  pass


@rule
def example_plugin_rule(root_type: RootType) -> PluginProduct:
  return PluginProduct()


class LoaderTestBase:
  def setup_method(self):
    self.build_configuration = BuildConfiguration()
    self.working_set = WorkingSet()
    for entry in working_set.entries:
      self.working_set.add_entry(entry)

  def teardown_method(self):
    Goal.clear()

  @staticmethod
  def get_mock_plugin(name, version, reg=None, alias=None, after=None, rules=None):
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
    :param callable rules: Optional callable for rules entry point
    """

    plugin_pkg = f'demoplugin{uuid.uuid4().hex}'
    pkg = types.ModuleType(plugin_pkg)
    sys.modules[plugin_pkg] = pkg
    module_name = f'{plugin_pkg}.demo'
    plugin = types.ModuleType(module_name)
    setattr(pkg, 'demo', plugin)
    sys.modules[module_name] = plugin

    metadata = {}
    entry_lines = []

    if reg is not None:
      setattr(plugin, 'foo', reg)
      entry_lines.append(f'register_goals = {module_name}:foo\n')

    if alias is not None:
      setattr(plugin, 'bar', alias)
      entry_lines.append(f'build_file_aliases = {module_name}:bar\n')

    if after is not None:
      setattr(plugin, 'baz', after)
      entry_lines.append(f'load_after = {module_name}:baz\n')

    if rules is not None:
      setattr(plugin, 'qux', rules)
      entry_lines.append(f'rules = {module_name}:qux\n')

    if entry_lines:
      entry_data = '[pantsbuild.plugin]\n{}\n'.format('\n'.join(entry_lines))
      metadata = {'entry_points.txt': entry_data}

    return Distribution(project_name=name, version=version, metadata=MockMetadata(metadata))

  def load_plugins(self, plugins, v1_register):
    load_plugins(self.build_configuration, plugins, self.working_set, v1_register=v1_register)

  @contextmanager
  def create_register(self, build_file_aliases=None, register_goals=None, global_subsystems=None,
                      rules=None, module_name='register'):

    package_name = f'__test_package_{uuid.uuid4().hex}'
    assert package_name not in sys.modules

    package_module = types.ModuleType(package_name)
    sys.modules[package_name] = package_module
    try:
      register_module_fqn = f'{package_name}.{module_name}'
      register_module = types.ModuleType(register_module_fqn)
      setattr(package_module, module_name, register_module)
      sys.modules[register_module_fqn] = register_module

      def register_entrypoint(function_name, function):
        if function:
          setattr(register_module, function_name, function)

      register_entrypoint('build_file_aliases', build_file_aliases)
      register_entrypoint('global_subsystems', global_subsystems)
      register_entrypoint('register_goals', register_goals)
      register_entrypoint('rules', rules)

      yield package_name
    finally:
      del sys.modules[package_name]

  def assert_empty_aliases(self):
    registered_aliases = self.build_configuration.registered_aliases()
    assert 0 == len(registered_aliases.target_types)
    assert 0 == len(registered_aliases.target_macro_factories)
    assert 0 == len(registered_aliases.objects)
    assert 0 == len(registered_aliases.context_aware_object_factories)
    assert self.build_configuration.optionables() == set()
    assert 0 == len(self.build_configuration.rules())


@pytest.mark.parametrize('v1_register', [False, True])
class TestV1V2Loader(LoaderTestBase):
  """Tests for functionality that is expected not to differ based on the v1_register option."""

  def test_load_valid_empty(self, v1_register):
    with self.create_register() as backend_package:
      load_backend(self.build_configuration, backend_package, v1_register=v1_register)
      self.assert_empty_aliases()

  def test_load_valid_partial_aliases(self, v1_register):
    aliases = BuildFileAliases(targets={'bob': DummyTarget},
                               objects={'obj1': DummyObject1,
                                        'obj2': DummyObject2})
    with self.create_register(build_file_aliases=lambda: aliases) as backend_package:
      load_backend(self.build_configuration, backend_package, v1_register=v1_register)
      registered_aliases = self.build_configuration.registered_aliases()
      assert DummyTarget == registered_aliases.target_types['bob']
      assert DummyObject1 == registered_aliases.objects['obj1']
      assert DummyObject2 == registered_aliases.objects['obj2']
      assert self.build_configuration.optionables() == {DummySubsystem1, DummySubsystem2}

  def test_load_invalid_entrypoint(self, v1_register):
    def build_file_aliases(bad_arg):
      return BuildFileAliases()

    with self.create_register(build_file_aliases=build_file_aliases) as backend_package:
      with pytest.raises(BuildConfigurationError):
        load_backend(self.build_configuration, backend_package, v1_register=v1_register)

  def test_load_invalid_module(self, v1_register):
    with self.create_register(module_name='register2') as backend_package:
      with pytest.raises(BuildConfigurationError):
        load_backend(self.build_configuration, backend_package, v1_register=v1_register)

  def test_load_missing_plugin(self, v1_register):
    with pytest.raises(PluginNotFound):
      self.load_plugins(['Foobar'], v1_register=v1_register)

  def test_plugin_installs_alias(self, v1_register):
    def reg_alias():
      return BuildFileAliases(targets={'pluginalias': DummyTarget},
                              objects={'FROMPLUGIN1': DummyObject1,
                                       'FROMPLUGIN2': DummyObject2})
    self.working_set.add(self.get_mock_plugin('aliasdemo', '0.0.1', alias=reg_alias))

    # Start with no aliases.
    self.assert_empty_aliases()

    # Now load the plugin which defines aliases.
    self.load_plugins(['aliasdemo'], v1_register=v1_register)

    # Aliases now exist.
    registered_aliases = self.build_configuration.registered_aliases()
    assert DummyTarget == registered_aliases.target_types['pluginalias']
    assert DummyObject1 == registered_aliases.objects['FROMPLUGIN1']
    assert DummyObject2 == registered_aliases.objects['FROMPLUGIN2']
    assert self.build_configuration.optionables() == {DummySubsystem1, DummySubsystem2}

  def test_rules(self, v1_register):
    def backend_rules():
      return [example_rule, RootRule(RootType)]
    with self.create_register(rules=backend_rules) as backend_package:
      load_backend(self.build_configuration, backend_package, v1_register=v1_register)
      assert self.build_configuration.rules() == [example_rule.rule, RootRule(RootType)]

    def plugin_rules():
      return [example_plugin_rule]

    self.working_set.add(self.get_mock_plugin('this-plugin-rules', '0.0.1', rules=plugin_rules))
    self.load_plugins(['this-plugin-rules'], v1_register=v1_register)
    assert self.build_configuration.rules() == [example_rule.rule, RootRule(RootType), example_plugin_rule.rule]

  def test_backend_plugin_ordering(self, v1_register):
    def reg_alias():
      return BuildFileAliases(targets={'override-alias': DummyTarget2})
    self.working_set.add(self.get_mock_plugin('pluginalias', '0.0.1', alias=reg_alias))
    plugins=['pluginalias==0.0.1']
    aliases = BuildFileAliases(targets={'override-alias': DummyTarget})
    with self.create_register(build_file_aliases=lambda: aliases) as backend_module:
      backends=[backend_module]
      load_backends_and_plugins(plugins, self.working_set, backends,
                                self.build_configuration, v1_register=v1_register)
    # The backend should load first, then the plugins, therefore the alias registered in
    # the plugin will override the alias registered by the backend
    registered_aliases = self.build_configuration.registered_aliases()
    assert DummyTarget2 == registered_aliases.target_types['override-alias']


class TestV1Loader(LoaderTestBase):
  """Tests for functionality that is expected to differ based on the v1_register option."""

  def test_load_valid_partial_goals(self):
    def register_goals():
      Goal.by_name('jack').install(TaskRegistrar('jill', DummyTask))

    with self.create_register(register_goals=register_goals) as backend_package:
      Goal.clear()
      assert 0 == len(Goal.all())

      load_backend(self.build_configuration, backend_package, v1_register=True)
      self.assert_empty_aliases()
      assert 1 == len(Goal.all())

      task_names = Goal.by_name('jack').ordered_task_names()
      assert 1 == len(task_names)

      task_name = task_names[0]
      assert 'jill' == task_name

  def test_plugin_load_and_order(self):
    d1 = self.get_mock_plugin('demo1', '0.0.1', after=lambda: ['demo2'])
    d2 = self.get_mock_plugin('demo2', '0.0.3')
    self.working_set.add(d1)

    # Attempting to load 'demo1' then 'demo2' should fail as 'demo1' requires 'after'=['demo2'].
    with pytest.raises(PluginLoadOrderError):
      self.load_plugins(['demo1', 'demo2'], v1_register=True)

    # Attempting to load 'demo2' first should fail as it is not (yet) installed.
    with pytest.raises(PluginNotFound):
      self.load_plugins(['demo2', 'demo1'], v1_register=True)

    # Installing demo2 and then loading in correct order should work though.
    self.working_set.add(d2)
    self.load_plugins(['demo2>=0.0.2', 'demo1'], v1_register=True)

    # But asking for a bad (not installed) version fails.
    with pytest.raises(VersionConflict):
      self.load_plugins(['demo2>=0.0.5'], v1_register=True)

  def test_plugin_installs_goal(self):
    def reg_goal():
      Goal.by_name('plugindemo').install(TaskRegistrar('foo', DummyTask))
    self.working_set.add(self.get_mock_plugin('regdemo', '0.0.1', reg=reg_goal))

    # Start without the custom goal.
    assert 0 == len(Goal.by_name('plugindemo').ordered_task_names())

    # Load plugin which registers custom goal, but with v1_register=False.
    self.load_plugins(['regdemo'], v1_register=False)

    # The custom goal isn't registered.
    assert 0 == len(Goal.by_name('plugindemo').ordered_task_names())

    # Load plugin which registers custom goal, with v1_register=True.
    self.load_plugins(['regdemo'], v1_register=True)

    # Now the custom goal exists.
    assert 1 == len(Goal.by_name('plugindemo').ordered_task_names())
    assert 'foo' == Goal.by_name('plugindemo').ordered_task_names()[0]

  def test_subsystems(self):
    def global_subsystems():
      return {DummySubsystem1, DummySubsystem2}
    with self.create_register(global_subsystems=global_subsystems) as backend_package:
      # Don't register global subsystems if v1_register=False.
      load_backend(self.build_configuration, backend_package, v1_register=False)
      assert self.build_configuration.optionables() == set()
      # Do register them otherwise.
      load_backend(self.build_configuration, backend_package, v1_register=True)
      assert self.build_configuration.optionables() == {DummySubsystem1, DummySubsystem2}
