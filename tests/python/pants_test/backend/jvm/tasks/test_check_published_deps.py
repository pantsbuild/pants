# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.scala_artifact import ScalaArtifact
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
from pants.backend.jvm.tasks.check_published_deps import CheckPublishedDeps
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants.java.jar.jar_dependency import JarDependency
from pants.testutil.task_test_base import ConsoleTaskTestBase
from pants.util.dirutil import safe_mkdir, safe_mkdtemp, safe_open
from pants.util.memo import memoized_classproperty


class CheckPublishedDepsTest(ConsoleTaskTestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(
            targets={"target": Target, "jar_library": JarLibrary, "java_library": JavaLibrary},
            objects={
                "artifact": Artifact,
                "jar": JarDependency,
                "scala_artifact": ScalaArtifact,
                "scala_jar": ScalaJarDependency,
            },
            context_aware_object_factories={
                "repo": lambda _: Repository(
                    name="repo", url="http://www.www.com", push_db_basedir=cls.push_db_basedir
                ),
            },
        )

    @classmethod
    def task_type(cls):
        return CheckPublishedDeps

    @memoized_classproperty
    def push_db_basedir(cls):
        return safe_mkdtemp()

    def assert_console_output(self, *args, **kwargs):
        # Ensure that JarPublish's repos option is set, as CheckPublishedDeps consults it.
        self.set_options_for_scope("publish.jar", repos={})
        return super().assert_console_output(*args, **kwargs)

    def setUp(self):
        super().setUp()

        safe_mkdir(self.push_db_basedir, clean=True)

        def write_db_file(relpath, contents):
            with safe_open(os.path.join(self.push_db_basedir, relpath), "w") as fp:
                fp.write(contents)

        write_db_file(
            "org.name/lib1/publish.properties",
            dedent(
                """
                revision.major.org.name%lib1=2
                revision.minor.org.name%lib1=0
                revision.patch.org.name%lib1=0
                revision.sha.org.name%lib1=12345
                """
            ),
        )
        write_db_file(
            "org.name/lib2/publish.properties",
            dedent(
                """
                revision.major.org.name%lib2=2
                revision.minor.org.name%lib2=0
                revision.patch.org.name%lib2=0
                revision.sha.org.name%lib2=12345
                """
            ),
        )

        self.add_to_build_file(
            "provider/BUILD",
            dedent(
                """
                java_library(name='lib1',
                  provides=artifact(
                    org='org.name',
                    name='lib1',
                    repo=repo),
                  sources=[])
                java_library(name='lib2',
                  provides=artifact(
                    org='org.name',
                    name='lib2',
                    repo=repo),
                  sources=[])
                """
            ),
        )
        self.add_to_build_file(
            "outdated/BUILD",
            dedent(
                """
                jar_library(name='outdated',
                  jars=[jar(org='org.name', name='lib1', rev='1.0.0')]
                )
                """
            ),
        )
        self.add_to_build_file(
            "uptodate/BUILD",
            dedent(
                """
                jar_library(name='uptodate',
                  jars=[jar(org='org.name', name='lib2', rev='2.0.0')]
                )
                """
            ),
        )
        self.add_to_build_file(
            "both/BUILD",
            dedent(
                """
                target(name='both',
                  dependencies=[
                    'outdated',
                    'uptodate',
                  ]
                )
                """
            ),
        )

    def test_all_up_to_date(self):
        self.assert_console_output(targets=[self.target("uptodate")])

    def test_print_up_to_date_and_outdated(self):
        self.assert_console_output(
            "outdated org.name#lib1 1.0.0 latest 2.0.0",
            "up-to-date org.name#lib2 2.0.0",
            targets=[self.target("both")],
            options={"print_uptodate": True},
        )

    def test_outdated(self):
        self.assert_console_output(
            "outdated org.name#lib1 1.0.0 latest 2.0.0", targets=[self.target("outdated")]
        )
