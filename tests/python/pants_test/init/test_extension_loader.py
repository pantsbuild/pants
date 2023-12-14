# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
import types
import unittest
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

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
from pants.engine.rules import rule
from pants.engine.target import COMMON_TARGET_FIELDS, Target
from pants.init.backend_templating import TemplatedBackendConfig
from pants.init.extension_loader import (
    PluginLoadOrderError,
    PluginNotFound,
    load_backend,
    load_backends_and_plugins,
    load_plugins,
)
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


class MockMetadata(EmptyProvider):
    def __init__(self, metadata):
        self.metadata = metadata

    def has_metadata(self, name):
        return name in self.metadata

    def get_metadata(self, name):
        return self.metadata[name]

    def get_metadata_lines(self, name):
        return yield_lines(self.get_metadata(name))


class DummySubsystem(Subsystem):
    options_scope = "dummy-subsystem"


class DummyTarget(Target):
    alias = "dummy_tgt"
    core_fields = COMMON_TARGET_FIELDS


class DummyTarget2(Target):
    alias = "dummy_tgt2"
    core_fields = ()


class DummyObject1:
    pass


class DummyObject2:
    pass


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


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.bc_builder = BuildConfiguration.Builder()
        self.working_set = WorkingSet()
        for entry in working_set.entries:
            self.working_set.add_entry(entry)

    @contextmanager
    def create_package(
        self,
        build_file_aliases=None,
        rules=None,
        target_types=None,
        generate=None,
        module_name="register",
    ):
        package_name = f"__test_package_{uuid.uuid4().hex}"
        self.assertFalse(package_name in sys.modules)

        package_module = types.ModuleType(package_name)
        sys.modules[package_name] = package_module
        try:
            register_module_fqn = f"{package_name}.{module_name}"
            register_module = types.ModuleType(register_module_fqn)
            setattr(package_module, module_name, register_module)
            sys.modules[register_module_fqn] = register_module

            def register_entrypoint(function_name, function):
                if function:
                    setattr(register_module, function_name, function)

            register_entrypoint("build_file_aliases", build_file_aliases)
            register_entrypoint("rules", rules)
            register_entrypoint("target_types", target_types)
            register_entrypoint("generate", generate)

            yield package_name
        finally:
            del sys.modules[package_name]

    def assert_empty(self):
        build_configuration = self.bc_builder.create()
        registered_aliases = build_configuration.registered_aliases
        self.assertEqual(0, len(registered_aliases.objects))
        self.assertEqual(0, len(registered_aliases.context_aware_object_factories))
        self.assertEqual(build_configuration.subsystem_to_providers, FrozenDict())
        self.assertEqual(0, len(build_configuration.rules))
        self.assertEqual(0, len(build_configuration.target_types))

    def test_load_valid_empty(self):
        with self.create_package() as backend_package:
            load_backend(self.bc_builder, backend_package)
            self.assert_empty()

    def test_load_valid_partial_aliases(self):
        aliases = BuildFileAliases(objects={"obj1": DummyObject1, "obj2": DummyObject2})
        with self.create_package(build_file_aliases=lambda: aliases) as backend_package:
            load_backend(self.bc_builder, backend_package)
            build_configuration = self.bc_builder.create()
            registered_aliases = build_configuration.registered_aliases
            self.assertEqual(DummyObject1, registered_aliases.objects["obj1"])
            self.assertEqual(DummyObject2, registered_aliases.objects["obj2"])

    def test_load_invalid_entrypoint(self):
        def build_file_aliases(bad_arg):
            return BuildFileAliases()

        with self.create_package(build_file_aliases=build_file_aliases) as backend_package:
            with self.assertRaises(BuildConfigurationError):
                load_backend(self.bc_builder, backend_package)

    def test_load_invalid_module(self):
        with self.create_package(module_name="register2") as backend_package:
            with self.assertRaises(BuildConfigurationError):
                load_backend(self.bc_builder, backend_package)

    def test_load_missing_plugin(self):
        with self.assertRaises(PluginNotFound):
            self.load_plugins(["Foobar"])

    @staticmethod
    def get_mock_plugin(
        name, version, reg=None, alias=None, after=None, rules=None, target_types=None
    ):
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
        :param callable target_types: Optional callable for target_types entry point
        """

        plugin_pkg = f"demoplugin{uuid.uuid4().hex}"
        pkg = types.ModuleType(plugin_pkg)
        sys.modules[plugin_pkg] = pkg
        module_name = f"{plugin_pkg}.demo"
        plugin = types.ModuleType(module_name)
        setattr(pkg, "demo", plugin)
        sys.modules[module_name] = plugin

        metadata = {}
        entry_lines = []

        if reg is not None:
            setattr(plugin, "foo", reg)
            entry_lines.append(f"register_goals = {module_name}:foo\n")

        if alias is not None:
            setattr(plugin, "bar", alias)
            entry_lines.append(f"build_file_aliases = {module_name}:bar\n")

        if after is not None:
            setattr(plugin, "baz", after)
            entry_lines.append(f"load_after = {module_name}:baz\n")

        if rules is not None:
            setattr(plugin, "qux", rules)
            entry_lines.append(f"rules = {module_name}:qux\n")

        if target_types is not None:
            setattr(plugin, "tofu", target_types)
            entry_lines.append(f"target_types = {module_name}:tofu\n")

        if entry_lines:
            entry_data = "[pantsbuild.plugin]\n{}\n".format("\n".join(entry_lines))
            metadata = {"entry_points.txt": entry_data}

        return Distribution(project_name=name, version=version, metadata=MockMetadata(metadata))

    def load_plugins(self, plugins):
        load_plugins(self.bc_builder, plugins, self.working_set)

    def test_plugin_load_and_order(self):
        d1 = self.get_mock_plugin("demo1", "0.0.1", after=lambda: ["demo2"])
        d2 = self.get_mock_plugin("demo2", "0.0.3")
        self.working_set.add(d1)

        # Attempting to load 'demo1' then 'demo2' should fail as 'demo1' requires 'after'=['demo2'].
        with self.assertRaises(PluginLoadOrderError):
            self.load_plugins(["demo1", "demo2"])

        # Attempting to load 'demo2' first should fail as it is not (yet) installed.
        with self.assertRaises(PluginNotFound):
            self.load_plugins(["demo2", "demo1"])

        # Installing demo2 and then loading in correct order should work though.
        self.working_set.add(d2)
        self.load_plugins(["demo2>=0.0.2", "demo1"])

        # But asking for a bad (not installed) version fails.
        with self.assertRaises(VersionConflict):
            self.load_plugins(["demo2>=0.0.5"])

    def test_plugin_installs_alias(self):
        def reg_alias():
            return BuildFileAliases(
                objects={"FROMPLUGIN1": DummyObject1, "FROMPLUGIN2": DummyObject2},
            )

        self.working_set.add(self.get_mock_plugin("aliasdemo", "0.0.1", alias=reg_alias))

        # Start with no aliases.
        self.assert_empty()

        # Now load the plugin which defines aliases.
        self.load_plugins(["aliasdemo"])

        # Aliases now exist.
        build_configuration = self.bc_builder.create()
        registered_aliases = build_configuration.registered_aliases
        self.assertEqual(DummyObject1, registered_aliases.objects["FROMPLUGIN1"])
        self.assertEqual(DummyObject2, registered_aliases.objects["FROMPLUGIN2"])

    def test_rules(self):
        def backend_rules():
            return [example_rule]

        with self.create_package(rules=backend_rules) as backend_package:
            load_backend(self.bc_builder, backend_package)
            self.assertEqual(self.bc_builder.create().rules, FrozenOrderedSet([example_rule.rule]))

        def plugin_rules():
            return [example_plugin_rule]

        self.working_set.add(self.get_mock_plugin("this-plugin-rules", "0.0.1", rules=plugin_rules))
        self.load_plugins(["this-plugin-rules"])
        self.assertEqual(
            self.bc_builder.create().rules,
            FrozenOrderedSet([example_rule.rule, example_plugin_rule.rule]),
        )

    def test_templated_backend_rules(self):
        @dataclass
        class GeneratedBackend:
            _rules: list

            def rules(self):
                return self._rules

        def generate(backend_package_alias: str, kwargs: dict):
            config_arg1 = kwargs["config_arg1"]

            @dataclass(frozen=True)
            class TemplatedWrapperType:
                value: Any

            @rule(canonical_name_suffix=backend_package_alias)
            def wrap_root_type(root_type: RootType) -> TemplatedWrapperType:
                return TemplatedWrapperType((root_type.value, config_arg1))

            return GeneratedBackend([wrap_root_type])

        with self.create_package(
            generate=generate, module_name="mock_backend_generator"
        ) as package:
            load_backend(
                self.bc_builder,
                backend_package="foo_backend",
                templating_config=TemplatedBackendConfig.from_dict(
                    {
                        "template": package + ".mock_backend_generator",
                        "config_arg1": "FOO",
                    }
                ),
            )
            load_backend(
                self.bc_builder,
                backend_package="bar_backend",
                templating_config=TemplatedBackendConfig.from_dict(
                    {
                        "template": package + ".mock_backend_generator",
                        "config_arg1": "BAR",
                    }
                ),
            )

        build_configuration = self.bc_builder.create()
        rules = build_configuration.rules
        self.assertEqual(len(rules), 2)

        providers_to_rule = {p: r for r, p in build_configuration.rule_to_providers.items()}
        foo_rule = providers_to_rule[("foo_backend",)]
        self.assertEqual(foo_rule.func(RootType("a")).value, ("a", "FOO"))
        self.assertEqual(foo_rule.canonical_name.split(".")[-1], "wrap_root_type_foo_backend")

        bar_rule = providers_to_rule[("bar_backend",)]
        self.assertEqual(bar_rule.func(RootType("a")).value, ("a", "BAR"))
        self.assertEqual(bar_rule.canonical_name.split(".")[-1], "wrap_root_type_bar_backend")

    def test_target_types(self):
        def target_types():
            return [DummyTarget, DummyTarget2]

        with self.create_package(target_types=target_types) as backend_package:
            load_backend(self.bc_builder, backend_package)
            assert self.bc_builder.create().target_types == (DummyTarget, DummyTarget2)

        class PluginTarget(Target):
            alias = "plugin_tgt"
            core_fields = ()

        def plugin_targets():
            return [PluginTarget]

        self.working_set.add(
            self.get_mock_plugin("new-targets", "0.0.1", target_types=plugin_targets)
        )
        self.load_plugins(["new-targets"])
        assert self.bc_builder.create().target_types == (DummyTarget, DummyTarget2, PluginTarget)

    def test_backend_plugin_ordering(self):
        def reg_alias():
            return BuildFileAliases(objects={"override-alias": DummyObject2})

        self.working_set.add(self.get_mock_plugin("pluginalias", "0.0.1", alias=reg_alias))
        plugins = ["pluginalias==0.0.1"]
        aliases = BuildFileAliases(objects={"override-alias": DummyObject1})
        with self.create_package(build_file_aliases=lambda: aliases) as backend_module:
            backends = [backend_module]
            build_configuration = load_backends_and_plugins(
                plugins, self.working_set, backends, bc_builder=self.bc_builder
            )
        # The backend should load first, then the plugins, therefore the alias registered in
        # the plugin will override the alias registered by the backend
        registered_aliases = build_configuration.registered_aliases
        self.assertEqual(DummyObject2, registered_aliases.objects["override-alias"])
