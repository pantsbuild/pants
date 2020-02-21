# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.build_graph.intermediate_target_factory import hash_target
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class IntermediateTargetIntegrationTest(PantsRunIntegrationTest):
    def test_scoped(self):
        test_path = "testprojects/src/java/org/pantsbuild/testproject/runtime"
        scoped_address = "3rdparty:gson"
        stdout_list = self.run_pants(["-q", "list", f"{test_path}:"]).stdout_data.strip().split()

        hash_1 = hash_target(scoped_address, "compile")
        hash_2 = hash_target(scoped_address, "runtime")
        self.assertIn(
            f"testprojects/src/java/org/pantsbuild/testproject/runtime:gson-unstable-compile-{hash_1}",
            stdout_list,
        )

        self.assertIn(
            f"testprojects/src/java/org/pantsbuild/testproject/runtime:gson-unstable-runtime-{hash_2}",
            stdout_list,
        )

    def test_intransitive(self):
        test_path = "testprojects/src/java/org/pantsbuild/testproject/intransitive"
        stdout_list = self.run_pants(["-q", "list", f"{test_path}:"]).stdout_data.strip().split()
        suffix = "intransitive"

        hash_b = hash_target(f"{test_path}:b", suffix)
        hash_c = hash_target(f"{test_path}:c", suffix)

        self.assertIn(
            f"testprojects/src/java/org/pantsbuild/testproject/intransitive:b-unstable-{suffix}-{hash_b}",
            stdout_list,
        )

        self.assertIn(
            f"testprojects/src/java/org/pantsbuild/testproject/intransitive:c-unstable-{suffix}-{hash_c}",
            stdout_list,
        )

    def test_provided(self):
        test_path = "testprojects/maven_layout/provided_patching"
        stdout_list = self.run_pants(["-q", "list", f"{test_path}::"]).stdout_data.strip().split()
        suffix = "provided"

        hash_1 = hash_target(
            "testprojects/maven_layout/provided_patching/one/src/main/java:shadow", suffix
        )
        hash_2 = hash_target(
            "testprojects/maven_layout/provided_patching/two/src/main/java:shadow", suffix
        )
        hash_3 = hash_target(
            "testprojects/maven_layout/provided_patching/three/src/main/java:shadow", suffix
        )

        self.assertIn(
            f"testprojects/maven_layout/provided_patching/one/src/main/java:shadow-unstable-{suffix}-{hash_1}",
            stdout_list,
        )

        self.assertIn(
            f"testprojects/maven_layout/provided_patching/two/src/main/java:shadow-unstable-{suffix}-{hash_2}",
            stdout_list,
        )

        self.assertIn(
            f"testprojects/maven_layout/provided_patching/three/src/main/java:shadow-unstable-{suffix}-{hash_3}",
            stdout_list,
        )

        self.assertIn(
            f"testprojects/maven_layout/provided_patching/leaf:shadow-unstable-{suffix}-{hash_2}",
            stdout_list,
        )

    def test_no_redundant_target(self):
        # TODO: Create another BUILD.other file with same provided scope,
        # once we resolve https://github.com/pantsbuild/pants/issues/3933
        test_path = "testprojects/maven_layout/provided_patching/one/src/main/java"
        stdout_list = self.run_pants(["-q", "list", f"{test_path}::"]).stdout_data.strip().split()
        suffix = "provided"

        hash = hash_target(f"{test_path}:shadow", suffix)
        synthetic_target = f"{test_path}:shadow-unstable-{suffix}-{hash}"
        self.assertEqual(stdout_list.count(synthetic_target), 1)
