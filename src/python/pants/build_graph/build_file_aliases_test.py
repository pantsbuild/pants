# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import pytest

from pants.build_graph.build_file_aliases import BuildFileAliases


class TestBuildFileAliasesTest:
    def test_create(self):
        assert BuildFileAliases(objects={}, context_aware_object_factories={}) == BuildFileAliases()
        objects = {"jane": 42}
        assert BuildFileAliases(
            objects=objects, context_aware_object_factories={}
        ) == BuildFileAliases(objects=objects)
        factories = {"jim": lambda ctx: "bob"}
        assert BuildFileAliases(
            objects={}, context_aware_object_factories=factories
        ) == BuildFileAliases(context_aware_object_factories=factories)
        assert BuildFileAliases(
            objects=objects, context_aware_object_factories={}
        ) == BuildFileAliases(objects=objects)
        assert BuildFileAliases(
            objects=objects, context_aware_object_factories=factories
        ) == BuildFileAliases(objects=objects, context_aware_object_factories=factories)

    def test_bad_context_aware_object_factories(self):
        with pytest.raises(TypeError):
            BuildFileAliases(context_aware_object_factories={"george": 1})

    def test_merge(self):
        def e_factory(ctx):
            return "e"

        def f_factory(ctx):
            return "f"

        first = BuildFileAliases(objects={"d": 2}, context_aware_object_factories={"e": e_factory})

        second = BuildFileAliases(
            objects={"c": 1, "d": 42},
            context_aware_object_factories={"f": f_factory},
        )

        expected = BuildFileAliases(
            # second overrides first
            objects={"d": 42, "c": 1},
            # combine
            context_aware_object_factories={"e": e_factory, "f": f_factory},
        )
        assert expected == first.merge(second)
