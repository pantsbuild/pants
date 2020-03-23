# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.resources import Resources
from pants.testutil.test_base import TestBase


class PythonTargetTest(TestBase):
    def test_validation(self):
        internal_repo = Repository(url=None, push_db_basedir=None)
        # Adding a JVM Artifact as a provides on a PythonTarget doesn't make a lot of sense.
        # This test sets up that very scenario, and verifies that pants throws a
        # TargetDefinitionException.
        with self.assertRaises(TargetDefinitionException):
            self.make_target(
                target_type=PythonTarget,
                spec=":one",
                provides=Artifact(org="com.twitter", name="one-jar", repo=internal_repo),
            )

        spec = "//:test-with-PythonArtifact"
        pa = PythonArtifact(name="foo", version="1.0", description="foo")

        # This test verifies that adding a 'setup_py' provides to a PythonTarget is okay.
        pt_with_artifact = self.make_target(spec=spec, target_type=PythonTarget, provides=pa)
        self.assertEqual(pt_with_artifact.address.spec, spec)

        spec = "//:test-with-none"
        # This test verifies that having no provides is okay.
        pt_no_artifact = self.make_target(spec=spec, target_type=PythonTarget, provides=None)
        self.assertEqual(pt_no_artifact.address.spec, spec)

    def assert_single_resource_dep(
        self, target, expected_resource_path, expected_resource_contents
    ):
        self.assertEqual(1, len(target.dependencies))
        resources_dep = target.dependencies[0]
        self.assertIsInstance(resources_dep, Resources)

        self.assertEqual(1, len(target.resources))
        resources_tgt = target.resources[0]
        self.assertIs(resources_dep, resources_tgt)

        self.assertEqual([expected_resource_path], resources_tgt.sources_relative_to_buildroot())
        resource_rel_path = resources_tgt.sources_relative_to_buildroot()[0]
        with open(os.path.join(self.build_root, resource_rel_path)) as fp:
            self.assertEqual(expected_resource_contents, fp.read())
        return resources_tgt

    def test_resource_dependencies(self):
        self.create_file("res/data.txt", contents="1/137")
        res = self.make_target(spec="res:resources", target_type=Resources, sources=["data.txt"])
        lib = self.make_target(
            spec="test:lib", target_type=PythonLibrary, sources=[], dependencies=[res]
        )
        resource_dep = self.assert_single_resource_dep(
            lib, expected_resource_path="res/data.txt", expected_resource_contents="1/137"
        )
        self.assertIs(res, resource_dep)
