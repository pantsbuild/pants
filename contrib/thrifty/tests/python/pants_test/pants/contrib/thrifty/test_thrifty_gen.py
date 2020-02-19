# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.wire.java.register import build_file_aliases as register_codegen
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.build_graph.register import build_file_aliases as register_core
from pants.java.jar.jar_dependency import JarDependency
from pants.testutil.task_test_base import TaskTestBase

from pants.contrib.thrifty.java_thrifty_gen import JavaThriftyGen
from pants.contrib.thrifty.java_thrifty_library import JavaThriftyLibrary


class JavaThriftyGenTest(TaskTestBase):
    TARGET_WORKDIR = ".pants.d/bogus/workdir"

    @classmethod
    def task_type(cls):
        return JavaThriftyGen

    @classmethod
    def alias_groups(cls):
        return register_core().merge(register_codegen())

    def _create_fake_thrifty_tool(self):
        self.make_target(
            ":thrifty-compiler",
            JarLibrary,
            jars=[
                JarDependency(org="com.microsoft.thrifty", name="thrifty-compiler", rev="0.4.3"),
            ],
        )

    def test_compiler_args(self):
        self._create_fake_thrifty_tool()
        target = self.make_target(
            "src/thrifty:simple-thrifty-target", JavaThriftyLibrary, sources=["foo.thrift"]
        )
        context = self.context(target_roots=[target])
        task = self.create_task(context)
        self.assertEqual(
            [
                f"--out={self.TARGET_WORKDIR}",
                f"--path={self.build_root}/src/thrifty",
                "src/thrifty/foo.thrift",
            ],
            task.format_args_for_target(target, self.TARGET_WORKDIR),
        )

    def test_compiler_args_deps(self):
        self._create_fake_thrifty_tool()
        upstream = self.make_target(
            "src/thrifty:upstream", JavaThriftyLibrary, sources=["upstream.thrift"]
        )
        downstream = self.make_target(
            "src/thrifty:downstream",
            JavaThriftyLibrary,
            sources=["downstream.thrift"],
            dependencies=[upstream],
        )
        context = self.context(target_roots=[upstream, downstream])
        task = self.create_task(context)
        self.assertEqual(
            [
                f"--out={self.TARGET_WORKDIR}",
                f"--path={self.build_root}/src/thrifty",
                "src/thrifty/downstream.thrift",
            ],
            task.format_args_for_target(downstream, self.TARGET_WORKDIR),
        )
