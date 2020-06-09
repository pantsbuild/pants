# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
from typing import List

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.consolidate_classpath import ConsolidateClasspath
from pants.build_graph.resources import Resources
from pants.java.jar.jar_dependency import JarDependency
from pants.util.dirutil import safe_file_dump
from pants_test.backend.jvm.tasks.jvm_binary_task_test_base import JvmBinaryTaskTestBase


class TestConsolidateClasspath(JvmBinaryTaskTestBase):
    @classmethod
    def task_type(cls):
        return ConsolidateClasspath

    def setUp(self):
        """Prepare targets, context, runtime classpath."""
        super().setUp()
        self.task = self.prepare_execute(self.context())

        self.jar_artifact = self.create_artifact(org="org.example", name="foo", rev="1.0.0")
        self.zip_artifact = self.create_artifact(
            org="org.pantsbuild", name="bar", rev="2.0.0", ext="zip"
        )
        self.bundle_artifact = self.create_artifact(
            org="org.apache", name="baz", rev="3.0.0", classifier="tests"
        )
        self.tar_gz_artifact = self.create_artifact(
            org="org.gnu", name="gary", rev="4.0.0", ext="tar.gz"
        )

        self.jar_lib = self.make_target(
            spec="3rdparty/jvm/org/example:foo",
            target_type=JarLibrary,
            jars=[
                JarDependency(org="org.example", name="foo", rev="1.0.0"),
                JarDependency(org="org.pantsbuild", name="bar", rev="2.0.0", ext="zip"),
                JarDependency(org="org.apache", name="baz", rev="3.0.0", classifier="tests"),
                JarDependency(org="org.gnu", name="gary", rev="4.0.0", ext="tar.gz"),
            ],
        )

        safe_file_dump(os.path.join(self.build_root, "resources/foo/file"), "// dummy content")
        self.resources_target = self.make_target(
            "//resources:foo-resources", Resources, sources=["foo/file"]
        )

        # This is so that payload fingerprint can be computed.
        safe_file_dump(os.path.join(self.build_root, "foo/Foo.java"), "// dummy content")
        self.java_lib_target = self.make_target(
            "//foo:foo-library", JavaLibrary, sources=["Foo.java"]
        )

        self.binary_target = self.make_target(
            spec="//foo:foo-binary",
            target_type=JvmBinary,
            dependencies=[self.java_lib_target, self.jar_lib, self.resources_target],
        )

        self.dist_root = os.path.join(self.build_root, "dist")

    def _setup_classpath(self, task_context):
        """As a separate prep step because to test different option settings, this needs to rerun
        after context is re-created."""
        self.ensure_classpath_products(task_context)
        self.add_to_runtime_classpath(
            task_context, self.binary_target, {"Foo.class": "", "foo.txt": "", "foo/file": ""}
        )

    def test_remove_raw_deps(self):
        """Test default setting outputs bundle products using `target.id`."""
        self.app_target = self.make_target(
            spec="//foo:foo-app",
            target_type=JvmApp,
            basename="FooApp",
            dependencies=[self.binary_target],
        )
        self.task_context = self.context(target_roots=[self.app_target])
        self._setup_classpath(self.task_context)
        self.execute(self.task_context)
        task_dir = os.path.join(
            self.pants_workdir, "pants_backend_jvm_tasks_consolidate_classpath_ConsolidateClasspath"
        )
        found_files = [os.path.basename(f) for f in self.iter_files(task_dir)]
        consolidate_classpath_jar = self.find_consolidate_classpath_jar(found_files)
        self.assertEqual(
            sorted([consolidate_classpath_jar, "Foo.class", "foo.txt", "file"]), sorted(found_files)
        )

        # Confirm that we haven't destroyed deps.
        expected_non_deps = {consolidate_classpath_jar, "Foo.class", "foo.txt", "file"}
        found = set(os.listdir(self.pants_workdir))
        print(expected_non_deps - found)
        self.assertTrue(expected_non_deps - found == expected_non_deps)

    def test_consolidate_classpath(self):
        """Test default setting outputs bundle products using `target.id`."""
        self.app_target = self.make_target(
            spec="//foo:foo-app",
            target_type=JvmApp,
            basename="FooApp",
            dependencies=[self.binary_target],
        )
        self.task_context = self.context(target_roots=[self.app_target])
        self._setup_classpath(self.task_context)
        self.execute(self.task_context)
        task_dir = os.path.join(
            self.pants_workdir, "pants_backend_jvm_tasks_consolidate_classpath_ConsolidateClasspath"
        )
        found_files = [os.path.basename(f) for f in self.iter_files(task_dir)]
        consolidate_classpath_jar = self.find_consolidate_classpath_jar(found_files)
        self.assertEqual(
            sorted([consolidate_classpath_jar, "Foo.class", "foo.txt", "file"]), sorted(found_files)
        )

        # Confirm that we haven't destroyed deps.
        expected_deps = {
            "org.apache-baz-3.0.0-tests.jar",
            "org.example-foo-1.0.0.jar",
            "org.gnu-gary-4.0.0.tar.gz",
            "org.pantsbuild-bar-2.0.0.zip",
        }
        found = set(os.listdir(self.pants_workdir))
        self.assertTrue(expected_deps - found == set())

    @staticmethod
    def find_consolidate_classpath_jar(files: List[str]) -> str:
        matching = [f for f in files if re.match(r"output-[0-9a-f]{6}\.jar", f)]
        if len(matching) == 1:
            return matching[0]
        raise ValueError(f"Could not find single consolidate classpath jar in {files}.")
