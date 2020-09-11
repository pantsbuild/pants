# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

import pytest

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import open_zip, temporary_dir


@pytest.mark.skip(reason="times out")
class BinaryCreateIntegrationTest(PantsRunIntegrationTest):
    def test_autovalue_classfiles(self):
        self.build_and_run(
            pants_args=["binary", "examples/src/java/org/pantsbuild/example/autovalue"],
            rel_out_path="dist",
            java_args=["-jar", "autovalue.jar"],
            expected_output="Hello Autovalue!",
        )

    def test_manifest_entries(self):
        self.build_and_run(
            pants_args=[
                "binary",
                "testprojects/src/java/org/pantsbuild/testproject/manifest:manifest-with-source",
            ],
            rel_out_path="dist",
            java_args=[
                "-cp",
                "manifest-with-source.jar",
                "org.pantsbuild.testproject.manifest.Manifest",
            ],
            expected_output="Hello World!  Version: 1.2.3",
        )

    def test_manifest_entries_no_source(self):
        self.build_and_run(
            pants_args=[
                "binary",
                "testprojects/src/java/org/pantsbuild/testproject/manifest:manifest-no-source",
            ],
            rel_out_path="dist",
            java_args=[
                "-cp",
                "manifest-no-source.jar",
                "org.pantsbuild.testproject.manifest.Manifest",
            ],
            expected_output="Hello World!  Version: 4.5.6",
        )

    def test_manifest_entries_bundle(self):
        # package level manifest entry, in this case, `Implementation-Version`, no longer work
        # because package files are not included in the bundle jar, instead they are referenced
        # through its manifest's Class-Path.
        self.build_and_run(
            pants_args=[
                "bundle",
                "testprojects/src/java/org/pantsbuild/testproject/manifest:manifest-app",
            ],
            rel_out_path=os.path.join(
                "dist",
                (
                    "testprojects.src.java.org.pantsbuild.testproject"
                    ".manifest.manifest-app-bundle"
                ),
            ),
            java_args=[
                "-cp",
                "manifest-no-source.jar",
                "org.pantsbuild.testproject.manifest.Manifest",
            ],
            expected_output="Hello World!  Version: null",
        )

        # If we still want to get package level manifest entries, we need to include packages files
        # in the bundle jar through `--deployjar`. However use that with caution because the monolithic
        # jar may have multiple packages.
        self.build_and_run(
            pants_args=[
                "bundle",
                "testprojects/src/java/org/pantsbuild/testproject/manifest:manifest-app",
                "--bundle-jvm-deployjar",
            ],
            rel_out_path=os.path.join(
                "dist",
                (
                    "testprojects.src.java.org.pantsbuild.testproject"
                    ".manifest.manifest-app-bundle"
                ),
            ),
            java_args=[
                "-cp",
                "manifest-no-source.jar",
                "org.pantsbuild.testproject.manifest.Manifest",
            ],
            expected_output="Hello World!  Version: 4.5.6",
        )

    def test_agent_dependency(self):
        directory = "testprojects/src/java/org/pantsbuild/testproject/manifest"
        target = f"{directory}:manifest-with-agent"
        with self.temporary_workdir() as workdir:
            pants_run = self.run_pants_with_workdir(["binary", target], workdir=workdir)
            self.assert_success(pants_run)
            jar = "dist/manifest-with-agent.jar"
            with open_zip(jar, mode="r") as j:
                with j.open("META-INF/MANIFEST.MF") as jar_entry:
                    normalized_lines = (
                        line.decode().strip() for line in jar_entry.readlines() if line.strip()
                    )
                    entries = {tuple(line.split(": ", 2)) for line in normalized_lines}
                    self.assertIn(
                        ("Agent-Class", "org.pantsbuild.testproject.manifest.Agent"), entries
                    )

    def test_deploy_excludes(self):
        with temporary_dir() as distdir:

            def build(name):
                jar_filename = os.path.join(distdir, f"{name}.jar")
                command = [
                    f"--pants-distdir={distdir}",
                    "--no-compile-rsc-capture-classpath",
                    "binary",
                    f"testprojects/src/java/org/pantsbuild/testproject/deployexcludes:{name}",
                ]
                self.assert_success(self.run_pants(command))
                return jar_filename

            # The excluded binary should not contain any guava classes, and should fail to run.
            jar_filename = build("deployexcludes")
            with open_zip(jar_filename) as jar_file:
                self.assertEqual(
                    {
                        "META-INF/",
                        "META-INF/MANIFEST.MF",
                        "org/",
                        "org/pantsbuild/",
                        "org/pantsbuild/testproject/",
                        "org/pantsbuild/testproject/deployexcludes/",
                        "org/pantsbuild/testproject/deployexcludes/DeployExcludesMain.class",
                    },
                    set(jar_file.namelist()),
                )
            self.run_java(
                java_args=["-jar", jar_filename],
                expected_returncode=1,
                expected_output="java.lang.NoClassDefFoundError: "
                "com/google/common/collect/ImmutableSortedSet",
            )

            # And the non excluded binary should succeed.
            jar_filename = build("nodeployexcludes")
            self.run_java(
                java_args=["-jar", jar_filename], expected_output="DeployExcludes Hello World"
            )

    def build_and_run(self, pants_args, rel_out_path, java_args, expected_output):
        self.assert_success(self.run_pants(["clean-all"]))
        with self.pants_results(pants_args, {}) as pants_run:
            self.assert_success(pants_run)

            out_path = os.path.join(get_buildroot(), rel_out_path)
            self.run_java(java_args=java_args, expected_output=expected_output, cwd=out_path)

    def run_java(self, java_args, expected_returncode=0, expected_output=None, cwd=None):
        command = ["java"] + java_args
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
        stdout, stderr = process.communicate()
        stdout = stdout.decode()
        stderr = stderr.decode()

        self.assertEqual(
            expected_returncode,
            process.returncode,
            (
                "Expected exit code {} from command `{}` but got {}:\n"
                "stdout:\n{}\n"
                "stderr:\n{}".format(
                    expected_returncode, " ".join(command), process.returncode, stdout, stderr
                )
            ),
        )
        self.assertIn(expected_output, stdout if expected_returncode == 0 else stderr)
