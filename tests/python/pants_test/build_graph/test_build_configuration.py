# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.target import Target
from pants.engine.unions import UnionRule, union


class BuildConfigurationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.build_configuration = BuildConfiguration()

    def _register_aliases(self, **kwargs) -> None:
        self.build_configuration.register_aliases(BuildFileAliases(**kwargs))

    def test_register_bad(self) -> None:
        with self.assertRaises(TypeError):
            self.build_configuration.register_aliases(42)

    def test_register_target_alias(self) -> None:
        class Fred(Target):
            pass

        self._register_aliases(targets={"fred": Fred})
        aliases = self.build_configuration.registered_aliases()
        self.assertEqual({}, aliases.target_macro_factories)
        self.assertEqual({}, aliases.objects)
        self.assertEqual({}, aliases.context_aware_object_factories)
        self.assertEqual(dict(fred=Fred), aliases.target_types)

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
        aliases = self.build_configuration.registered_aliases()
        self.assertEqual({}, aliases.target_types)
        self.assertEqual({}, aliases.objects)
        self.assertEqual({}, aliases.context_aware_object_factories)
        self.assertEqual(dict(fred=factory), aliases.target_macro_factories)

    def test_register_exposed_object(self):
        self._register_aliases(objects={"jane": 42})
        aliases = self.build_configuration.registered_aliases()
        self.assertEqual({}, aliases.target_types)
        self.assertEqual({}, aliases.target_macro_factories)
        self.assertEqual({}, aliases.context_aware_object_factories)
        self.assertEqual(dict(jane=42), aliases.objects)

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
        aliases = self.build_configuration.registered_aliases()
        self.assertEqual({}, aliases.target_types)
        self.assertEqual({}, aliases.objects)
        self.assertEqual({}, aliases.target_macro_factories)
        self.assertEqual(
            {"func": caof_function, "cls": CaofClass}, aliases.context_aware_object_factories
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

        self.build_configuration.register_rules([UnionRule(Base, A)])
        self.build_configuration.register_rules([UnionRule(Base, B)])
        self.assertEqual(set(self.build_configuration.union_rules()[Base]), {A, B})
