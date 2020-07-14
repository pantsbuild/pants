# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.build_graph.build_file_aliases import BuildFileAliases


class BuildFileAliasesTest(unittest.TestCase):
    def test_create(self):
        self.assertEqual(
            BuildFileAliases(objects={}, context_aware_object_factories={}), BuildFileAliases(),
        )
        objects = {"jane": 42}
        self.assertEqual(
            BuildFileAliases(objects=objects, context_aware_object_factories={}),
            BuildFileAliases(objects=objects),
        )
        factories = {"jim": lambda ctx: "bob"}
        self.assertEqual(
            BuildFileAliases(objects={}, context_aware_object_factories=factories),
            BuildFileAliases(context_aware_object_factories=factories),
        )
        self.assertEqual(
            BuildFileAliases(objects=objects, context_aware_object_factories={}),
            BuildFileAliases(objects=objects),
        )
        self.assertEqual(
            BuildFileAliases(objects=objects, context_aware_object_factories=factories),
            BuildFileAliases(objects=objects, context_aware_object_factories=factories),
        )

    def test_bad_context_aware_object_factories(self):
        with self.assertRaises(TypeError):
            BuildFileAliases(context_aware_object_factories={"george": 1})

    def test_merge(self):
        e_factory = lambda ctx: "e"
        f_factory = lambda ctx: "f"

        first = BuildFileAliases(objects={"d": 2}, context_aware_object_factories={"e": e_factory})

        second = BuildFileAliases(
            objects={"c": 1, "d": 42}, context_aware_object_factories={"f": f_factory},
        )

        expected = BuildFileAliases(
            # second overrides first
            objects={"d": 42, "c": 1},
            # combine
            context_aware_object_factories={"e": e_factory, "f": f_factory},
        )
        self.assertEqual(expected, first.merge(second))
