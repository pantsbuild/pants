# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Type

import pytest

from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.goal import GoalSubsystem
from pants.engine.target import Target
from pants.engine.unions import UnionRule, union
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def bc_builder() -> BuildConfiguration.Builder:
    return BuildConfiguration.Builder()


def _register_aliases(bc_builder, **kwargs) -> None:
    bc_builder.register_aliases(BuildFileAliases(**kwargs))


def test_register_bad(bc_builder: BuildConfiguration.Builder) -> None:
    with pytest.raises(TypeError):
        bc_builder.register_aliases(42)


def test_register_exposed_object(bc_builder: BuildConfiguration.Builder) -> None:
    _register_aliases(bc_builder, objects={"jane": 42})
    aliases = bc_builder.create().registered_aliases
    assert FrozenDict() == aliases.context_aware_object_factories
    assert FrozenDict(jane=42) == aliases.objects


def test_register_exposed_context_aware_object_factory(
    bc_builder: BuildConfiguration.Builder,
) -> None:
    def caof_function(parse_context):
        return parse_context.rel_path

    class CaofClass:
        def __init__(self, parse_context):
            self._parse_context = parse_context

        def __call__(self):
            return self._parse_context.rel_path

    _register_aliases(
        bc_builder, context_aware_object_factories={"func": caof_function, "cls": CaofClass}
    )
    aliases = bc_builder.create().registered_aliases
    assert FrozenDict() == aliases.objects
    assert (
        FrozenDict({"func": caof_function, "cls": CaofClass})
        == aliases.context_aware_object_factories
    )


def test_register_union_rules(bc_builder: BuildConfiguration.Builder) -> None:
    @union
    class Base:
        pass

    class A:
        pass

    class B:
        pass

    union_a = UnionRule(Base, A)
    union_b = UnionRule(Base, B)
    bc_builder.register_rules("_dummy_for_test_", [union_a])
    bc_builder.register_rules("_dummy_for_test_", [union_b])
    assert bc_builder.create().union_rules == FrozenOrderedSet([union_a, union_b])


def test_validation(caplog, bc_builder: BuildConfiguration.Builder) -> None:
    def mk_dummy_subsys(_options_scope: str, goal: bool = False) -> Type[Subsystem]:
        class DummySubsystem(GoalSubsystem if goal else Subsystem):  # type: ignore[misc]
            options_scope = _options_scope

        return DummySubsystem

    def mk_dummy_tgt(_alias: str) -> Type[Target]:
        class DummyTarget(Target):
            alias = _alias
            core_fields = tuple()

        return DummyTarget

    bc_builder.register_subsystems(
        "_dummy_for_test_",
        (
            mk_dummy_subsys("foo"),
            mk_dummy_subsys("Bar-bar"),
            mk_dummy_subsys("baz"),
            mk_dummy_subsys("qux", goal=True),
            mk_dummy_subsys("global"),
        ),
    )
    bc_builder.register_target_types(
        "_dummy_for_test_", (mk_dummy_tgt("bar_bar"), mk_dummy_tgt("qux"), mk_dummy_tgt("global"))
    )
    with pytest.raises(TypeError) as e:
        bc_builder.create()
    assert (
        "Naming collision: `Bar-bar`/`bar_bar` is registered as a subsystem and a "
        "target type." in caplog.text
    )
    assert "Naming collision: `qux` is registered as a goal and a target type." in caplog.text
    assert (
        "Naming collision: `global` is registered as a reserved name, a subsystem "
        "and a target type." in caplog.text
    )
    assert "Found naming collisions" in str(e)


def test_register_subsystems(bc_builder: BuildConfiguration.Builder) -> None:
    def mk_dummy_subsys(_options_scope: str) -> Type[Subsystem]:
        class DummySubsystem(Subsystem):
            options_scope = _options_scope

        return DummySubsystem

    foo = mk_dummy_subsys("foo")
    bar = mk_dummy_subsys("bar")
    baz = mk_dummy_subsys("baz")
    bc_builder.register_subsystems("backend1", [foo, bar])
    bc_builder.register_subsystems("backend2", [bar, baz])
    bc_builder.register_subsystems("backend3", [baz])
    bc = bc_builder.create()

    assert bc.subsystem_to_providers == FrozenDict(
        {
            foo: ("backend1",),
            bar: ("backend1", "backend2"),
            baz: (
                "backend2",
                "backend3",
            ),
        }
    )


def test_register_target_types(bc_builder: BuildConfiguration.Builder) -> None:
    def mk_dummy_tgt(_alias: str) -> Type[Target]:
        class DummyTarget(Target):
            alias = _alias
            core_fields = tuple()

        return DummyTarget

    foo = mk_dummy_tgt("foo")
    bar = mk_dummy_tgt("bar")
    baz = mk_dummy_tgt("baz")
    bc_builder.register_target_types("backend1", [foo, bar])
    bc_builder.register_target_types("backend2", [bar, baz])
    bc_builder.register_target_types("backend3", [baz])
    bc = bc_builder.create()

    assert bc.target_type_to_providers == FrozenDict(
        {
            foo: ("backend1",),
            bar: ("backend1", "backend2"),
            baz: (
                "backend2",
                "backend3",
            ),
        }
    )
