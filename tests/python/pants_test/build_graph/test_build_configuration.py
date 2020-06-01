# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.target import Target
from pants.engine.unions import UnionRule, union
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


class BuildConfigurationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.bc_builder = BuildConfiguration.Builder()

    def _register_aliases(self, **kwargs) -> None:
        self.bc_builder.register_aliases(BuildFileAliases(**kwargs))

    def test_register_bad(self) -> None:
        with self.assertRaises(TypeError):
            self.bc_builder.register_aliases(42)

    def test_register_target_alias(self) -> None:
        class Fred(Target):
            pass

        self._register_aliases(targets={"fred": Fred})
        aliases = self.bc_builder.create().registered_aliases()
        self.assertEqual(FrozenDict(), aliases.target_macro_factories)
        self.assertEqual(FrozenDict(), aliases.objects)
        self.assertEqual(FrozenDict(), aliases.context_aware_object_factories)
        self.assertEqual(FrozenDict(fred=Fred), aliases.target_types)

    def test_register_target_macro_factory(self) -> None:
        class Fred(Target):
            pass

        class FredMacro(TargetMacro):
            def __init__(self, parse_context):
                self._parse_context = parse_context

            def expand(self, *args, **kwargs):
                return self._parse_context.create_object(
                    Fred, name="frog", dependencies=[kwargs["name"]]
                )

        class FredFactory(TargetMacro.Factory):
            @property
            def target_types(self):
                return {Fred}

            def macro(self, parse_context):
                return FredMacro(parse_context)

        factory = FredFactory()

        self._register_aliases(targets={"fred": factory})
        aliases = self.bc_builder.create().registered_aliases()
        self.assertEqual(FrozenDict(), aliases.target_types)
        self.assertEqual(FrozenDict(), aliases.objects)
        self.assertEqual(FrozenDict(), aliases.context_aware_object_factories)
        self.assertEqual(FrozenDict(fred=factory), aliases.target_macro_factories)

    def test_register_exposed_object(self):
        self._register_aliases(objects={"jane": 42})
        aliases = self.bc_builder.create().registered_aliases()
        self.assertEqual(FrozenDict(), aliases.target_types)
        self.assertEqual(FrozenDict(), aliases.target_macro_factories)
        self.assertEqual(FrozenDict(), aliases.context_aware_object_factories)
        self.assertEqual(FrozenDict(jane=42), aliases.objects)

    def test_register_exposed_context_aware_object_factory(self):
        def caof_function(parse_context):
            return parse_context.rel_path

        class CaofClass:
            def __init__(self, parse_context):
                self._parse_context = parse_context

            def __call__(self):
                return self._parse_context.rel_path

        self._register_aliases(
            context_aware_object_factories={"func": caof_function, "cls": CaofClass}
        )
        aliases = self.bc_builder.create().registered_aliases()
        self.assertEqual(FrozenDict(), aliases.target_types)
        self.assertEqual(FrozenDict(), aliases.objects)
        self.assertEqual(FrozenDict(), aliases.target_macro_factories)
        self.assertEqual(
            FrozenDict({"func": caof_function, "cls": CaofClass}),
            aliases.context_aware_object_factories,
        )

    def test_register_union_rules(self) -> None:
        # Two calls to register_rules should merge relevant unions.
        @union
        class Base:
            pass

        class A:
            pass

        class B:
            pass

        self.bc_builder.register_rules([UnionRule(Base, A)])
        self.bc_builder.register_rules([UnionRule(Base, B)])
        self.assertEqual(self.bc_builder.create().union_rules()[Base], FrozenOrderedSet([A, B]))
