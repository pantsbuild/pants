# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import re

import pytest

from pants.base.build_environment import get_buildroot
from pants.build_graph.intermediate_target_factory import hash_target
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.collections import ensure_str_list
from pants_test.backend.project_info.tasks.resolve_jars_test_mixin import ResolveJarsTestMixin


@pytest.mark.skip(reason="flaky")
class ExportIntegrationTest(ResolveJarsTestMixin, PantsRunIntegrationTest):
    _confs_args = [
        "--export-libraries-sources",
        "--export-libraries-javadocs",
    ]

    def run_export(
        self, test_target, workdir, load_libs=False, only_default=False, extra_args=None
    ):
        """Runs ./pants export ... and returns its json output.

        :param string|list test_target: spec of the targets to run on.
        :param string workdir: working directory to run pants with.
        :param bool load_libs: whether to load external libraries (of any conf).
        :param bool only_default: if loading libraries, whether to only resolve the default conf, or to
          additionally resolve sources and javadocs.
        :param list extra_args: list of extra arguments for the pants invocation.
        :return: the json output of the console task.
        :rtype: dict
        """
        export_out_file = os.path.join(workdir, "export_out.txt")
        args = [
            "export",
            f"--output-file={export_out_file}",
            *ensure_str_list(test_target, allow_single_str=True),
        ]
        libs_args = ["--no-export-libraries"] if not load_libs else self._confs_args
        if load_libs and only_default:
            libs_args = []
        pants_run = self.run_pants_with_workdir(args + libs_args + (extra_args or []), workdir)
        self.assert_success(pants_run)
        self.assertTrue(
            os.path.exists(export_out_file),
            msg=f"Could not find export output file in {export_out_file}",
        )
        with open(export_out_file, "r") as json_file:
            json_data = json.load(json_file)
            if not load_libs:
                self.assertIsNone(json_data.get("libraries"))
            return json_data

    def evaluate_subtask(self, targets, workdir, load_extra_confs, extra_args, expected_jars):
        json_data = self.run_export(
            targets,
            workdir,
            load_libs=True,
            only_default=not load_extra_confs,
            extra_args=extra_args,
        )
        for jar in expected_jars:
            self.assertIn(jar, json_data["libraries"])
            for path in json_data["libraries"][jar].values():
                self.assertTrue(os.path.exists(path), f"Expected jar at {path} to actually exist.")

    def test_export_code_gen(self):
        with self.temporary_workdir() as workdir:
            test_target = "examples/tests/java/org/pantsbuild/example/usethrift:usethrift"
            json_data = self.run_export(test_target, workdir, load_libs=True)
            thrift_target_name = (
                "examples.src.thrift.org.pantsbuild.example.precipitation" ".precipitation-java"
            )
            codegen_target_regex = os.path.join(
                os.path.relpath(workdir, get_buildroot()),
                f"gen/thrift-java/[^/]*/[^/:]*/[^/:]*:{thrift_target_name}",
            )
            p = re.compile(codegen_target_regex)
            self.assertTrue(any(p.match(target) for target in json_data.get("targets").keys()))

    def test_export_json_transitive_jar(self):
        with self.temporary_workdir() as workdir:
            test_target = "examples/tests/java/org/pantsbuild/example/usethrift:usethrift"
            json_data = self.run_export(test_target, workdir, load_libs=True)
            targets = json_data.get("targets")
            self.assertIn("org.hamcrest:hamcrest-core:1.3", targets[test_target]["libraries"])

    def test_export_jar_path_with_excludes(self):
        with self.temporary_workdir() as workdir:
            test_target = "testprojects/src/java/org/pantsbuild/testproject/exclude:foo"
            json_data = self.run_export(test_target, workdir, load_libs=True)
            self.assertIsNone(
                json_data.get("libraries").get("com.typesafe.sbt:incremental-compiler:0.13.7")
            )
            foo_target = json_data.get("targets").get(
                "testprojects/src/java/org/pantsbuild/testproject/exclude:foo"
            )
            self.assertTrue("com.typesafe.sbt:incremental-compiler" in foo_target.get("excludes"))

    def test_export_jar_path_with_excludes_soft(self):
        with self.temporary_workdir() as workdir:
            test_target = "testprojects/src/java/org/pantsbuild/testproject/exclude:"
            json_data = self.run_export(
                test_target,
                workdir,
                load_libs=True,
                extra_args=["--no-export-allow-global-excludes"],
            )
            self.assertIsNotNone(
                json_data.get("libraries").get("com.martiansoftware:nailgun-server:0.9.1")
            )
            self.assertIsNotNone(json_data.get("libraries").get("org.pantsbuild:jmake:1.3.8-10"))
            foo_target = json_data.get("targets").get(
                "testprojects/src/java/org/pantsbuild/testproject/exclude:foo"
            )
            self.assertTrue("com.typesafe.sbt:incremental-compiler" in foo_target.get("excludes"))
            self.assertTrue("org.pantsbuild" in foo_target.get("excludes"))

    def test_export_jar_path(self):
        with self.temporary_workdir() as workdir:
            test_target = "examples/tests/java/org/pantsbuild/example/usethrift:usethrift"
            json_data = self.run_export(test_target, workdir, load_libs=True)
            common_lang_lib_info = json_data.get("libraries").get("junit:junit:4.12")
            self.assertIsNotNone(common_lang_lib_info)
            self.assertIn("junit-4.12.jar", common_lang_lib_info.get("default"))
            self.assertIn("junit-4.12-javadoc.jar", common_lang_lib_info.get("javadoc"))
            self.assertIn("junit-4.12-sources.jar", common_lang_lib_info.get("sources"))

    def test_dep_map_for_java_sources(self):
        with self.temporary_workdir() as workdir:
            test_target = "examples/src/scala/org/pantsbuild/example/scala_with_java_sources"
            json_data = self.run_export(test_target, workdir)
            targets = json_data.get("targets")
            self.assertIn(
                "examples/src/java/org/pantsbuild/example/java_sources:java_sources", targets
            )

    def test_sources_and_javadocs(self):
        with self.temporary_workdir() as workdir:
            test_target = "testprojects/src/scala/org/pantsbuild/testproject/unicode/shapeless"
            json_data = self.run_export(test_target, workdir, load_libs=True)
            shapeless_lib = json_data.get("libraries").get("com.chuusai:shapeless_2.12:2.3.2")
            self.assertIsNotNone(shapeless_lib)
            self.assertIsNotNone(shapeless_lib["default"])
            self.assertIsNotNone(shapeless_lib["sources"])
            self.assertIsNotNone(shapeless_lib["javadoc"])

    def test_classifiers(self):
        with self.temporary_workdir() as workdir:
            test_target = (
                "testprojects/tests/java/org/pantsbuild/testproject/ivyclassifier:ivyclassifier"
            )
            json_data = self.run_export(test_target, workdir, load_libs=True)
            avro_lib_info = json_data.get("libraries").get("org.apache.avro:avro:1.7.7")
            self.assertIsNotNone(avro_lib_info)
            self.assertIn(
                "avro-1.7.7.jar", avro_lib_info.get("default"),
            )
            self.assertIn(
                "avro-1.7.7-tests.jar", avro_lib_info.get("tests"),
            )
            self.assertIn(
                "avro-1.7.7-javadoc.jar", avro_lib_info.get("javadoc"),
            )
            self.assertIn(
                "avro-1.7.7-sources.jar", avro_lib_info.get("sources"),
            )

    def test_distributions_and_platforms(self):
        with self.temporary_workdir() as workdir:
            test_target = "examples/src/java/org/pantsbuild/example/hello/simple"
            json_data = self.run_export(
                test_target,
                workdir,
                load_libs=False,
                extra_args=[
                    "--jvm-platform-default-platform=java8",
                    "--jvm-platform-platforms={"
                    ' "java8": {"source": "1.8", "target": "1.8", "args": [ "-X123" ]},'
                    ' "java11": {"source": "11", "target": "11", "args": [ "-X456" ]}'
                    "}",
                    "--jvm-distributions-paths={"
                    ' "macos": [ "/Library/JDK" ],'
                    ' "linux": [ "/usr/lib/jdk8", "/usr/lib/jdk11"]'
                    "}",
                ],
            )
            self.assertFalse("python_setup" in json_data)
            target_name = "examples/src/java/org/pantsbuild/example/hello/simple:simple"
            targets = json_data.get("targets")
            self.assertEqual("java8", targets[target_name]["platform"])
            self.assertEqual(
                {
                    "default_platform": "java8",
                    "platforms": {
                        "java8": {"source_level": "1.8", "args": ["-X123"], "target_level": "1.8"},
                        "java11": {"source_level": "11", "args": ["-X456"], "target_level": "11"},
                    },
                },
                json_data["jvm_platforms"],
            )

    def test_runtime_platform(self):
        with self.temporary_workdir() as workdir:
            test_target = (
                "testprojects/tests/java/org/pantsbuild/testproject/testjvms:eight-runtime-platform"
            )
            json_data = self.run_export(test_target, workdir)
            self.assertEqual("java7", json_data["targets"][test_target]["platform"])
            self.assertEqual("java8", json_data["targets"][test_target]["runtime_platform"])

    def test_intransitive_and_scope(self):
        with self.temporary_workdir() as workdir:
            test_path = "testprojects/maven_layout/provided_patching/one/src/main/java"
            test_target = f"{test_path}:common"
            json_data = self.run_export(test_target, workdir)
            h = hash_target(f"{test_path}:shadow", "provided")
            synthetic_target = f"{test_path}:shadow-unstable-provided-{h}"
            self.assertEqual(False, json_data["targets"][synthetic_target]["transitive"])
            self.assertEqual("compile test", json_data["targets"][synthetic_target]["scope"])

    def test_export_properly_marks_target_roots(self):
        with self.temporary_workdir() as workdir:
            # We use this directory because it has subdirectories, so the `::` glob captures multiple
            # targets, and it also depends on an examples/src/resources outside of the directory.
            test_path = "examples/src/java/org/pantsbuild/example/hello"
            json_data = self.run_export(f"{test_path}::", workdir, load_libs=False)
            for target_address, attributes in json_data["targets"].items():
                if target_address.startswith(test_path):
                    self.assertTrue(attributes["is_target_root"])
                else:
                    self.assertFalse(attributes["is_target_root"])
