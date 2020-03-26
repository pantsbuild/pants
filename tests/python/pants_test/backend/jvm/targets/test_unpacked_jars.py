# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.java.jar.jar_dependency import JarDependency
from pants.testutil.test_base import TestBase


class UnpackedJarsTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(
            targets={"jar_library": JarLibrary, "unpacked_jars": UnpackedJars},
            objects={"jar": JarDependency},
        )

    def test_empty_libraries(self):
        with self.assertRaises(UnpackedJars.ExpectedLibrariesError):
            self.make_target(":foo", UnpackedJars)

    def test_simple(self):
        self.make_target(":import_jars", JarLibrary, jars=[JarDependency("foo", "bar", "123")])
        target = self.make_target(":foo", UnpackedJars, libraries=[":import_jars"])

        self.assertIsInstance(target, UnpackedJars)
        dependency_specs = [
            spec for spec in target.compute_dependency_address_specs(payload=target.payload)
        ]
        self.assertSequenceEqual([":import_jars"], dependency_specs)
        self.assertEqual(1, len(target.all_imported_jar_deps))
        import_jar_dep = target.all_imported_jar_deps[0]
        self.assertIsInstance(import_jar_dep, JarDependency)

    def test_bad_libraries_ref(self):
        self.make_target(":right-type", JarLibrary, jars=[JarDependency("foo", "bar", "123")])
        # Making a target which is not a jar library, which causes an error.
        self.make_target(":wrong-type", UnpackedJars, libraries=[":right-type"])
        target = self.make_target(":foo", UnpackedJars, libraries=[":wrong-type"])
        with self.assertRaises(ImportJarsMixin.WrongTargetTypeError):
            target.imported_targets

    def test_has_all_imported_jar_deps(self):
        def assert_dep(dep, org, name, rev):
            self.assertTrue(isinstance(dep, JarDependency))
            self.assertEqual(org, dep.org)
            self.assertEqual(name, dep.name)
            self.assertEqual(rev, dep.rev)

        self.add_to_build_file(
            "BUILD",
            dedent(
                """
                jar_library(name='lib1',
                  jars=[
                    jar(org='testOrg1', name='testName1', rev='123'),
                  ],
                )
                jar_library(name='lib2',
                  jars=[
                    jar(org='testOrg2', name='testName2', rev='456'),
                    jar(org='testOrg3', name='testName3', rev='789'),
                  ],
                )
                unpacked_jars(name='unpacked-lib',
                  libraries=[':lib1', ':lib2'],
                )
                """
            ),
        )
        lib1 = self.target("//:lib1")
        self.assertIsInstance(lib1, JarLibrary)
        self.assertEqual(1, len(lib1.jar_dependencies))
        assert_dep(lib1.jar_dependencies[0], "testOrg1", "testName1", "123")

        lib2 = self.target("//:lib2")
        self.assertIsInstance(lib2, JarLibrary)
        self.assertEqual(2, len(lib2.jar_dependencies))
        assert_dep(lib2.jar_dependencies[0], "testOrg2", "testName2", "456")
        assert_dep(lib2.jar_dependencies[1], "testOrg3", "testName3", "789")

        unpacked_lib = self.target("//:unpacked-lib")
        unpacked_jar_deps = unpacked_lib.all_imported_jar_deps

        self.assertEqual(3, len(unpacked_jar_deps))
        assert_dep(unpacked_jar_deps[0], "testOrg1", "testName1", "123")
        assert_dep(unpacked_jar_deps[1], "testOrg2", "testName2", "456")
        assert_dep(unpacked_jar_deps[2], "testOrg3", "testName3", "789")
