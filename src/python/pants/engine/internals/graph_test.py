# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.engine.addresses import Address, Addresses
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    Target,
    Targets,
    TransitiveTarget,
    TransitiveTargets,
    WrappedTarget,
)
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase
from pants.util.ordered_set import FrozenOrderedSet


class MockTarget(Target):
    alias = "target"
    core_fields = (Dependencies,)


class GraphTest(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), RootRule(Addresses), RootRule(WrappedTarget))

    @classmethod
    def target_types(cls):
        return (MockTarget,)

    def test_transitive_targets(self) -> None:
        t1 = MockTarget({}, address=Address.parse(":t1"))
        t2 = MockTarget({Dependencies.alias: [t1.address]}, address=Address.parse(":t2"))
        d1 = MockTarget({Dependencies.alias: [t1.address]}, address=Address.parse(":d1"))
        d2 = MockTarget({Dependencies.alias: [t2.address]}, address=Address.parse(":d2"))
        d3 = MockTarget({}, address=Address.parse(":d3"))
        root = MockTarget(
            {Dependencies.alias: [d1.address, d2.address, d3.address]},
            address=Address.parse(":root"),
        )

        self.add_to_build_file(
            "",
            dedent(
                """\
                target(name='t1')
                target(name='t2', dependencies=[':t1'])
                target(name='d1', dependencies=[':t1'])
                target(name='d2', dependencies=[':t2'])
                target(name='d3')
                target(name='root', dependencies=[':d1', ':d2', ':d3'])
                """
            ),
        )

        direct_deps = self.request_single_product(
            Targets, Params(DependenciesRequest(root[Dependencies]), create_options_bootstrapper())
        )
        assert direct_deps == Targets([d1, d2, d3])

        transitive_target = self.request_single_product(
            TransitiveTarget, Params(WrappedTarget(root), create_options_bootstrapper())
        )
        assert transitive_target.root == root
        assert {
            dep_transitive_target.root for dep_transitive_target in transitive_target.dependencies
        } == {d1, d2, d3}

        transitive_targets = self.request_single_product(
            TransitiveTargets,
            Params(Addresses([root.address, d2.address]), create_options_bootstrapper()),
        )
        assert transitive_targets.roots == (root, d2)
        assert transitive_targets.closure == FrozenOrderedSet([root, d2, d1, d3, t2, t1])
