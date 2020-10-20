# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from typing import Optional

from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.lifecycle import ExtensionLifecycleHandler, SessionLifecycleHandler
from pants.engine.unions import UnionRule, union
from pants.option.options import Options
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

    def test_register_exposed_object(self):
        self._register_aliases(objects={"jane": 42})
        aliases = self.bc_builder.create().registered_aliases
        assert FrozenDict() == aliases.context_aware_object_factories
        assert FrozenDict(jane=42) == aliases.objects

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
        aliases = self.bc_builder.create().registered_aliases
        assert FrozenDict() == aliases.objects
        assert (
            FrozenDict({"func": caof_function, "cls": CaofClass})
            == aliases.context_aware_object_factories
        )

    def test_register_union_rules(self) -> None:
        @union
        class Base:
            pass

        class A:
            pass

        class B:
            pass

        union_a = UnionRule(Base, A)
        union_b = UnionRule(Base, B)
        self.bc_builder.register_rules([union_a])
        self.bc_builder.register_rules([union_b])
        assert self.bc_builder.create().union_rules == FrozenOrderedSet([union_a, union_b])

    def test_register_lifecycle_handlers(self) -> None:
        class FooHandler(ExtensionLifecycleHandler):
            def on_session_create(
                self,
                *,
                build_root: str,
                options: Options,
                specs: Specs,
            ) -> Optional[SessionLifecycleHandler]:
                return None

        class BarHandler(ExtensionLifecycleHandler):
            def on_session_create(
                self,
                *,
                build_root: str,
                options: Options,
                specs: Specs,
            ) -> Optional[SessionLifecycleHandler]:
                return None

        self.bc_builder.register_lifecycle_handlers([FooHandler()])
        self.bc_builder.register_lifecycle_handlers([BarHandler()])
        bc = self.bc_builder.create()
        handlers = list(bc.lifecycle_handlers)
        assert isinstance(handlers[0], FooHandler)
        assert isinstance(handlers[1], BarHandler)
