# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from collections import OrderedDict

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_entry import ClasspathEntry
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.testutil.test_base import TestBase


class ClasspathUtilTest(TestBase):
    def test_path_with_differing_conf_ignored(self):
        a = self.make_target("a", JvmTarget)

        classpath_product = ClasspathProducts(self.pants_workdir)

        path = os.path.join(self.pants_workdir, "jar/path")
        classpath_product.add_for_target(a, [("default", path)])

        classpath = ClasspathUtil.compute_classpath(
            [a], classpath_product, extra_classpath_tuples=[], confs=["not-default"]
        )

        self.assertEqual([], classpath)

    def test_path_with_overlapped_conf_added(self):
        a = self.make_target("a", JvmTarget)

        classpath_product = ClasspathProducts(self.pants_workdir)

        path = os.path.join(self.pants_workdir, "jar/path")
        classpath_product.add_for_target(a, [("default", path)])

        classpath = ClasspathUtil.compute_classpath(
            [a], classpath_product, extra_classpath_tuples=[], confs=["not-default", "default"]
        )

        self.assertEqual([path], classpath)

    def test_extra_path_added(self):
        a = self.make_target("a", JvmTarget)

        classpath_product = ClasspathProducts(self.pants_workdir)

        path = os.path.join(self.pants_workdir, "jar/path")
        classpath_product.add_for_target(a, [("default", path)])

        extra_path = "new-path"
        extra_cp_tuples = [("default", extra_path)]
        classpath = ClasspathUtil.compute_classpath(
            [a], classpath_product, extra_classpath_tuples=extra_cp_tuples, confs=["default"]
        )

        self.assertEqual([path, extra_path], classpath)

    def test_classpath_by_targets(self):
        b = self.make_target("b", JvmTarget)
        a = self.make_target(
            "a", JvmTarget, dependencies=[b], excludes=[Exclude("com.example", "lib")]
        )

        classpath_products = ClasspathProducts(self.pants_workdir)

        path1 = self._path("jar/path1")
        path2 = self._path("jar/path2")
        path3 = os.path.join(self.pants_workdir, "jar/path3")
        resolved_jar = ResolvedJar(
            M2Coordinate(org="com.example", name="lib", rev="1.0"),
            cache_path="somewhere",
            pants_path=path3,
        )
        classpath_products.add_for_target(a, [("default", path1)])
        classpath_products.add_for_target(a, [("non-default", path2)])
        classpath_products.add_for_target(b, [("default", path2)])
        classpath_products.add_jars_for_targets([b], "default", [resolved_jar])
        classpath_products.add_excludes_for_targets([a])

        # (a, path2) filtered because of conf
        # (b, path3) filtered because of excludes
        self.assertEqual(
            OrderedDict([(a, [ClasspathEntry(path1)]), (b, [ClasspathEntry(path2)])]),
            ClasspathUtil.classpath_by_targets(a.closure(bfs=True), classpath_products),
        )

    def _path(self, p):
        return self.create_workdir_file(p)
