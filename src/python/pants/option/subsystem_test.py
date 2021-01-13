# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo
from pants.option.subsystem import Subsystem


class WorkunitSubscriptableSubsystem(Subsystem):
    options_scope = "dummy scope"

    def handle_workunits(self, **kwargs):
        pass


class DummySubsystem(Subsystem):
    options_scope = "dummy"


class DummyOptions:
    def for_scope(self, scope):
        return object()


class DummyOptionable(Optionable):
    options_scope = "foo"


class UninitializedSubsystem(Subsystem):
    options_scope = "uninitialized-scope"


class ScopedDependentSubsystem(Subsystem):
    options_scope = "scoped-dependent-subsystem"

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (DummySubsystem.scoped(cls),)


def si(scope, subsystem_cls):
    """Shorthand helper."""
    return ScopeInfo(scope, subsystem_cls)


def test_scoping_simple() -> None:
    assert {si("dummy", DummySubsystem)} == DummySubsystem.known_scope_infos()
    assert {
        si("scoped-dependent-subsystem", ScopedDependentSubsystem),
        si("dummy", DummySubsystem),
        si("dummy.scoped-dependent-subsystem", DummySubsystem),
    } == ScopedDependentSubsystem.known_scope_infos()


def test_scoping_tree() -> None:
    class SubsystemB(Subsystem):
        options_scope = "b"

    class SubsystemA(Subsystem):
        options_scope = "a"

        @classmethod
        def subsystem_dependencies(cls):
            return (DummySubsystem, SubsystemB)

    assert {
        si("dummy", DummySubsystem),
        si("a", SubsystemA),
        si("b", SubsystemB),
    } == SubsystemA.known_scope_infos()


def test_scoping_graph() -> None:
    class SubsystemB(Subsystem):
        options_scope = "b"

        @classmethod
        def subsystem_dependencies(cls):
            return (DummySubsystem,)

    class SubsystemA(Subsystem):
        options_scope = "a"

        @classmethod
        def subsystem_dependencies(cls):
            return (DummySubsystem, SubsystemB)

    assert {si("dummy", DummySubsystem), si("b", SubsystemB)} == SubsystemB.known_scope_infos()
    assert {
        si("dummy", DummySubsystem),
        si("a", SubsystemA),
        si("b", SubsystemB),
    } == SubsystemA.known_scope_infos()


def test_option_class_cycle() -> None:
    class SubsystemC(Subsystem):
        options_scope = "c"

        @classmethod
        def subsystem_dependencies(cls):
            return (SubsystemA,)

    class SubsystemB(Subsystem):
        options_scope = "b"

        @classmethod
        def subsystem_dependencies(cls):
            # Ensure that we detect cycles via scoped deps as well as global deps.
            return (SubsystemC.scoped(cls),)

    class SubsystemA(Subsystem):
        options_scope = "a"

        @classmethod
        def subsystem_dependencies(cls):
            return (SubsystemB,)

    for root in SubsystemA, SubsystemB, SubsystemC:
        with pytest.raises(Subsystem.CycleException):
            root.known_scope_infos()


def test_scoping_complex() -> None:
    """
    Subsystem dep structure is (-s-> = scoped dep, -g-> = global dep):

    D -s-> E
    |
    + -s->
          \
    A -s-> B -s-> C
           |
           + -g-> E
    """

    class SubsystemE(Subsystem):
        options_scope = "e"

    class SubsystemD(Subsystem):
        options_scope = "d"

        @classmethod
        def subsystem_dependencies(cls):
            return (SubsystemE.scoped(cls), SubsystemB.scoped(cls))

    class SubsystemC(Subsystem):
        options_scope = "c"

    class SubsystemB(Subsystem):
        options_scope = "b"

        @classmethod
        def subsystem_dependencies(cls):
            return (SubsystemE, SubsystemC.scoped(cls))

    class SubsystemA(Subsystem):
        options_scope = "a"

        @classmethod
        def subsystem_dependencies(cls):
            return (SubsystemB.scoped(cls),)

    assert set(SubsystemC.known_scope_infos()) == {si("c", SubsystemC)}
    assert set(SubsystemB.known_scope_infos()) == {
        si("b", SubsystemB),
        si("e", SubsystemE),
        si("c", SubsystemC),
        si("c.b", SubsystemC),
    }
    assert set(SubsystemA.known_scope_infos()) == {
        si("a", SubsystemA),
        si("e", SubsystemE),
        si("b", SubsystemB),
        si("b.a", SubsystemB),
        si("c", SubsystemC),
        si("c.b", SubsystemC),
        si("c.b.a", SubsystemC),
    }
    assert set(SubsystemD.known_scope_infos()) == {
        si("d", SubsystemD),
        si("e.d", SubsystemE),
        si("b", SubsystemB),
        si("b.d", SubsystemB),
        si("c", SubsystemC),
        si("c.b", SubsystemC),
        si("c.b.d", SubsystemC),
        si("e", SubsystemE),
    }


def test_subsystem_dependencies_iter() -> None:
    class SubsystemB(Subsystem):
        options_scope = "b"

    class SubsystemA(Subsystem):
        options_scope = "a"

        @classmethod
        def subsystem_dependencies(cls):
            return (DummySubsystem.scoped(cls), SubsystemB)

    dep_scopes = {dep.options_scope for dep in SubsystemA.subsystem_dependencies_iter()}
    assert {"b", "dummy.a"} == dep_scopes


def test_subsystem_closure_iter() -> None:
    class SubsystemA(Subsystem):
        options_scope = "a"

    class SubsystemB(Subsystem):
        options_scope = "b"

        @classmethod
        def subsystem_dependencies(cls):
            return (SubsystemA,)

    class SubsystemC(Subsystem):
        options_scope = "c"

        @classmethod
        def subsystem_dependencies(cls):
            return (SubsystemA, SubsystemB.scoped(cls))

    class SubsystemD(Subsystem):
        options_scope = "d"

        @classmethod
        def subsystem_dependencies(cls):
            return (SubsystemC, SubsystemB)

    dep_scopes = {dep.options_scope for dep in SubsystemD.subsystem_closure_iter()}
    assert {"c", "a", "b.c", "b"} == dep_scopes


def test_subsystem_closure_iter_cycle() -> None:
    class SubsystemA(Subsystem):
        options_scope = "a"

        @classmethod
        def subsystem_dependencies(cls):
            return (SubsystemB,)

    class SubsystemB(Subsystem):
        options_scope = "b"

        @classmethod
        def subsystem_dependencies(cls):
            return (SubsystemA,)

    with pytest.raises(Subsystem.CycleException):
        list(SubsystemB.subsystem_closure_iter())
