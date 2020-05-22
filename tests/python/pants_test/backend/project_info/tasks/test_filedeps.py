# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

from pants.backend.codegen.register import build_file_aliases as register_codegen
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.project_info.tasks.filedeps import FileDeps
from pants.build_graph.register import build_file_aliases as register_core
from pants.testutil.task_test_base import ConsoleTaskTestBase
from pants.testutil.test_base import AbstractTestGenerator


class FileDepsTest(ConsoleTaskTestBase, AbstractTestGenerator):
    @classmethod
    def alias_groups(cls):
        return register_core().merge(register_jvm()).merge(register_codegen())

    @classmethod
    def task_type(cls):
        return FileDeps

    def assert_console_output(self, *paths, **kwargs):
        if kwargs["options"]["absolute"]:
            paths = [os.path.join(self.build_root, path) for path in paths]

        super().assert_console_output(*paths, **kwargs)

    def setUp(self):
        super().setUp()
        self.context(options={"scala": {"runtime": ["tools:scala-library"]}})

        # TODO(John Sirois): Rationalize much of this target emission setup.  Lots of tests do similar
        # things: https://github.com/pantsbuild/pants/issues/525
        def create_target(path, definition, sources=None):
            if sources:
                self.create_files(path, sources)
            self.add_to_build_file(path, definition)

        create_target(
            path="src/scala/core",
            definition=dedent(
                """
                scala_library(
                  name='core',
                  sources=[
                    'core1.scala'
                  ],
                  java_sources=[
                    'src/java/core'
                  ]
                )
                """
            ),
            sources=["core1.scala"],
        )

        create_target(
            path="src/java/core",
            definition=dedent(
                """
                java_library(
                  name='core',
                  sources=['core*.java'],
                  dependencies=[
                    'src/scala/core'
                  ]
                )
                """
            ),
            sources=["core1.java", "core2.java"],
        )

        create_target(
            path="src/resources/lib",
            definition=dedent(
                """
                resources(
                  name='lib',
                  sources=['*.json'],
                )
                """
            ),
            sources=["data.json"],
        )

        create_target(
            path="src/thrift/storage",
            definition=dedent(
                """
                java_thrift_library(
                  name='storage',
                  sources=[
                    'data_types.thrift'
                  ]
                )
                """
            ),
            sources=["data_types.thrift"],
        )

        create_target(
            path="src/java/lib",
            definition=dedent(
                """
                java_library(
                  name='lib',
                  sources=[
                    'lib1.java'
                  ],
                  dependencies=[
                    'src/resources/lib',
                    'src/scala/core',
                    'src/thrift/storage'
                  ],
                )
                """
            ),
            sources=["lib1.java"],
        )

        # Derive a synthetic target from the src/thrift/storage thrift target as-if doing code-gen.
        self.create_file(".pants.d/gen/thrift/java/storage/Angle.java")
        self.make_target(
            spec=".pants.d/gen/thrift/java/storage",
            target_type=JavaLibrary,
            derived_from=self.target("src/thrift/storage"),
            sources=["Angle.java"],
        )
        synthetic_java_lib = self.target(".pants.d/gen/thrift/java/storage")

        java_lib = self.target("src/java/lib")
        java_lib.inject_dependency(synthetic_java_lib.address)

        create_target(
            path="src/java/bin",
            definition=dedent(
                """
                jvm_binary(
                  name='bin',
                  sources=['main.java'],
                  main='bin.Main',
                  dependencies=[
                    'src/java/lib'
                  ]
                )
                """
            ),
            sources=["main.java"],
        )

        create_target(
            path="project",
            definition=dedent(
                """
                jvm_app(
                  name='app',
                  binary='src/java/bin',
                  bundles=[
                    bundle(fileset=['config/app.yaml'])
                  ]
                )
                """
            ),
            sources=["config/app.yaml"],
        )

    @classmethod
    def generate_tests(cls):

        for is_absolute in [True, False]:

            def test_resources(self, is_absolute=is_absolute):
                self.assert_console_output(
                    "src/resources/lib/BUILD",
                    "src/resources/lib/data.json",
                    targets=[self.target("src/resources/lib")],
                    options=dict(absolute=is_absolute, transitive=True),
                )

            def test_globs(self, is_absolute=is_absolute):
                self.assert_console_output(
                    "src/scala/core/BUILD",
                    "src/scala/core/core1.scala",
                    "src/java/core/BUILD",
                    "src/java/core/core*.java",
                    targets=[self.target("src/scala/core")],
                    options=dict(globs=True, absolute=is_absolute, transitive=True),
                )

            def test_globs_app(self, is_absolute=is_absolute):
                self.assert_console_output(
                    "project/config/app.yaml",
                    "project/BUILD",
                    "src/java/bin/BUILD",
                    "src/java/core/BUILD",
                    "src/java/bin/main.java",
                    "src/java/core/core*.java",
                    "src/java/lib/BUILD",
                    "src/java/lib/lib1.java",
                    "src/resources/lib/*.json",
                    "src/resources/lib/BUILD",
                    "src/scala/core/BUILD",
                    "src/scala/core/core1.scala",
                    "src/thrift/storage/BUILD",
                    "src/thrift/storage/data_types.thrift",
                    targets=[self.target("project:app")],
                    options=dict(globs=True, absolute=is_absolute, transitive=True),
                )

            def test_scala_java_cycle_scala_end(self, is_absolute=is_absolute):
                self.assert_console_output(
                    "src/scala/core/BUILD",
                    "src/scala/core/core1.scala",
                    "src/java/core/BUILD",
                    "src/java/core/core1.java",
                    "src/java/core/core2.java",
                    targets=[self.target("src/scala/core")],
                    options=dict(absolute=is_absolute, transitive=True),
                )

            def test_scala_java_cycle_java_end(self, is_absolute=is_absolute):
                self.assert_console_output(
                    "src/scala/core/BUILD",
                    "src/scala/core/core1.scala",
                    "src/java/core/BUILD",
                    "src/java/core/core1.java",
                    "src/java/core/core2.java",
                    targets=[self.target("src/java/core")],
                    options=dict(absolute=is_absolute, transitive=True),
                )

            def test_concrete_only(self, is_absolute=is_absolute):
                self.assert_console_output(
                    "src/java/lib/BUILD",
                    "src/java/lib/lib1.java",
                    "src/thrift/storage/BUILD",
                    "src/thrift/storage/data_types.thrift",
                    "src/resources/lib/BUILD",
                    "src/resources/lib/data.json",
                    "src/scala/core/BUILD",
                    "src/scala/core/core1.scala",
                    "src/java/core/BUILD",
                    "src/java/core/core1.java",
                    "src/java/core/core2.java",
                    targets=[self.target("src/java/lib")],
                    options=dict(absolute=is_absolute, transitive=True),
                )

            def test_jvm_app(self, is_absolute=is_absolute):
                self.assert_console_output(
                    "project/BUILD",
                    "project/config/app.yaml",
                    "src/java/bin/BUILD",
                    "src/java/bin/main.java",
                    "src/java/lib/BUILD",
                    "src/java/lib/lib1.java",
                    "src/thrift/storage/BUILD",
                    "src/thrift/storage/data_types.thrift",
                    "src/resources/lib/BUILD",
                    "src/resources/lib/data.json",
                    "src/scala/core/BUILD",
                    "src/scala/core/core1.scala",
                    "src/java/core/BUILD",
                    "src/java/core/core1.java",
                    "src/java/core/core2.java",
                    targets=[self.target("project:app")],
                    options=dict(absolute=is_absolute, transitive=True),
                )

            for test_name, test in sorted(locals().items()):
                if test_name.startswith("test_"):
                    cls.add_test(f"{test_name}_{('abs_path' if is_absolute else 'rel_path')}", test)


FileDepsTest.generate_tests()
