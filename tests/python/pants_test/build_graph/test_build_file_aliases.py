# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest

from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.target import Target
from pants.engine.legacy.graph import LegacyBuildGraph
from pants.testutil.subsystem.util import init_subsystem
from pants.util.frozendict import FrozenDict


class BuildFileAliasesTest(unittest.TestCase):
    class BlueTarget(Target):
        pass

    def setUp(self):
        init_subsystem(Target.TagAssignments)
        self.target_macro_factory = TargetMacro.Factory.wrap(
            lambda ctx: ctx.create_object(
                self.BlueTarget, type_alias="jill", name=os.path.basename(ctx.rel_path)
            ),
            self.BlueTarget,
        )

    def test_create(self):
        self.assertEqual(
            BuildFileAliases(targets={}, objects={}, context_aware_object_factories={}),
            BuildFileAliases(),
        )

        targets = {"jake": Target, "jill": self.target_macro_factory}
        self.assertEqual(
            BuildFileAliases(targets=targets, objects={}, context_aware_object_factories={}),
            BuildFileAliases(targets=targets),
        )

        objects = {"jane": 42}
        self.assertEqual(
            BuildFileAliases(targets={}, objects=objects, context_aware_object_factories={}),
            BuildFileAliases(objects=objects),
        )

        factories = {"jim": lambda ctx: "bob"}
        self.assertEqual(
            BuildFileAliases(targets={}, objects={}, context_aware_object_factories=factories),
            BuildFileAliases(context_aware_object_factories=factories),
        )

        self.assertEqual(
            BuildFileAliases(targets=targets, objects=objects, context_aware_object_factories={}),
            BuildFileAliases(targets=targets, objects=objects),
        )

        self.assertEqual(
            BuildFileAliases(targets=targets, objects={}, context_aware_object_factories=factories),
            BuildFileAliases(targets=targets, context_aware_object_factories=factories),
        )

        self.assertEqual(
            BuildFileAliases(targets={}, objects=objects, context_aware_object_factories=factories),
            BuildFileAliases(objects=objects, context_aware_object_factories=factories),
        )

        self.assertEqual(
            BuildFileAliases(
                targets=targets, objects=objects, context_aware_object_factories=factories
            ),
            BuildFileAliases(
                targets=targets, objects=objects, context_aware_object_factories=factories
            ),
        )

    def test_create_bad_targets(self):
        with self.assertRaises(TypeError):
            BuildFileAliases(targets={"fred": object()})

        target = Target("fred", Address.parse("a:b"), LegacyBuildGraph(None, None))
        with self.assertRaises(TypeError):
            BuildFileAliases(targets={"fred": target})

    def test_create_bad_objects(self):
        with self.assertRaises(TypeError):
            BuildFileAliases(objects={"jane": Target})

        with self.assertRaises(TypeError):
            BuildFileAliases(objects={"jane": self.target_macro_factory})

    def test_bad_context_aware_object_factories(self):
        with self.assertRaises(TypeError):
            BuildFileAliases(context_aware_object_factories={"george": 1})

    def test_merge(self):
        e_factory = lambda ctx: "e"
        f_factory = lambda ctx: "f"

        first = BuildFileAliases(
            targets={"a": Target}, objects={"d": 2}, context_aware_object_factories={"e": e_factory}
        )

        second = BuildFileAliases(
            targets={"b": self.target_macro_factory},
            objects={"c": 1, "d": 42},
            context_aware_object_factories={"f": f_factory},
        )

        expected = BuildFileAliases(
            # nothing to merge
            targets={"a": Target, "b": self.target_macro_factory},
            # second overrides first
            objects={"d": 42, "c": 1},
            # combine
            context_aware_object_factories={"e": e_factory, "f": f_factory},
        )
        self.assertEqual(expected, first.merge(second))

    def test_target_types(self):
        aliases = BuildFileAliases(targets={"jake": Target, "jill": self.target_macro_factory})
        self.assertEqual(FrozenDict(jake=Target), aliases.target_types)

    def test_target_macro_factories(self):
        aliases = BuildFileAliases(targets={"jake": Target, "jill": self.target_macro_factory})
        self.assertEqual(FrozenDict(jill=self.target_macro_factory), aliases.target_macro_factories)

    def test_target_types_by_alias(self):
        aliases = BuildFileAliases(targets={"jake": Target, "jill": self.target_macro_factory})
        self.assertEqual(
            FrozenDict(jake=frozenset([Target]), jill=frozenset([self.BlueTarget])),
            aliases.target_types_by_alias,
        )
