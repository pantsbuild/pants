# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants.java.jar.jar_dependency import JarDependency
from pants.testutil.test_base import TestBase

jar1 = JarDependency(org="testOrg1", name="testName1", rev="123")
jar2 = JarDependency(org="testOrg2", name="testName2", rev="456")


class JarLibraryTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(targets={"jar_library": JarLibrary}, objects={"jar": JarDependency})

    def test_validation(self):
        target = Target(
            name="mybird", address=Address.parse("//:mybird"), build_graph=self.build_graph
        )
        # jars attribute must contain only JarLibrary instances
        with self.assertRaises(TargetDefinitionException):
            JarLibrary(name="test", jars=[target])

    def test_jar_dependencies(self):
        lib = JarLibrary(
            name="foo",
            address=Address.parse("//:foo"),
            build_graph=self.build_graph,
            jars=[jar1, jar2],
        )
        self.assertEqual((jar1, jar2), lib.jar_dependencies)

    def test_empty_jar_dependencies(self):
        def example():
            return self.make_target("//:foo", JarLibrary)

        self.assertRaises(TargetDefinitionException, example)

    def test_excludes(self):
        # TODO(Eric Ayers) There doesn't seem to be any way to set this field at the moment.
        lib = JarLibrary(
            name="foo", address=Address.parse("//:foo"), build_graph=self.build_graph, jars=[jar1]
        )
        self.assertEqual([], lib.excludes)
