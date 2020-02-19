# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

import pytest

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.scala_artifact import ScalaArtifact
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants.rules.core import list_targets
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class ListTargetsTest(GoalRuleTestBase):
    goal_cls = list_targets.List

    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(
            targets={
                "target": Target,
                "java_library": JavaLibrary,
                "python_library": PythonLibrary,
            },
            objects={
                "pants": lambda x: x,
                "artifact": Artifact,
                "scala_artifact": ScalaArtifact,
                "public": Repository(
                    name="public", url="http://maven.example.com", push_db_basedir="/tmp"
                ),
            },
        )

    @classmethod
    def rules(cls):
        return super().rules() + list_targets.rules()

    def setUp(self) -> None:
        super().setUp()

        # Setup a BUILD tree for various list tests
        class Lib:
            def __init__(self, name: str, provides: bool = False) -> None:
                self.name = name
                self.provides = (
                    dedent(
                        f"""
                        artifact(
                          org='com.example',
                          name='{name}',
                          repo=public
                        )
                        """
                    ).strip()
                    if provides
                    else "None"
                )

        def create_library(path: str, *libs: Lib) -> None:
            libs = libs or (Lib(os.path.basename(os.path.dirname(self.build_path(path)))),)
            for lib in libs:
                target = f"java_library(name='{lib.name}', provides={lib.provides}, sources=[])\n"
                self.add_to_build_file(path, target)

        create_library("a")
        create_library("a/b", Lib("b", provides=True))
        create_library("a/b/c", Lib("c"), Lib("c2", provides=True), Lib("c3"))
        create_library("a/b/d")
        create_library("a/b/e", Lib("e1"))
        self.add_to_build_file(
            "f",
            dedent(
                '''
                target(
                  name='alias',
                  dependencies=[
                    'a/b/c:c3',
                    'a/b/d:d',
                  ],
                  description = """
                Exercises alias resolution.
                Further description.
                  """,
                )
                '''
            ),
        )

    def test_list_all_empty(self):
        # NB: Also renders a warning to stderr, which is challenging to detect here but confirmed in:
        #   tests/python/pants_test/engine/legacy/test_list_integration.py
        self.assert_console_output(args=[])

    def test_list_path(self):
        self.assert_console_output("a/b:b", args=["a/b"])

    def test_list_siblings(self):
        self.assert_console_output("a/b:b", args=["a/b:"])
        self.assert_console_output("a/b/c:c", "a/b/c:c2", "a/b/c:c3", args=["a/b/c/:"])

    def test_list_descendants(self):
        self.assert_console_output("a/b/c:c", "a/b/c:c2", "a/b/c:c3", args=["a/b/c/::"])

        self.assert_console_output(
            "a/b:b", "a/b/c:c", "a/b/c:c2", "a/b/c:c3", "a/b/d:d", "a/b/e:e1", args=["a/b::"]
        )

    @pytest.mark.flaky(retries=1)  # https://github.com/pantsbuild/pants/issues/8678
    def test_list_all(self):
        self.assert_entries(
            "\n",
            "a:a",
            "a/b:b",
            "a/b/c:c",
            "a/b/c:c2",
            "a/b/c:c3",
            "a/b/d:d",
            "a/b/e:e1",
            "f:alias",
            args=["::"],
        )

        self.assert_entries(
            ", ",
            "a:a",
            "a/b:b",
            "a/b/c:c",
            "a/b/c:c2",
            "a/b/c:c3",
            "a/b/d:d",
            "a/b/e:e1",
            "f:alias",
            args=["--sep=, ", "::",],
        )

        self.assert_console_output(
            "a:a",
            "a/b:b",
            "a/b/c:c",
            "a/b/c:c2",
            "a/b/c:c3",
            "a/b/d:d",
            "a/b/e:e1",
            "f:alias",
            args=["::"],
        )

    def test_list_provides(self):
        self.assert_console_output(
            "a/b:b com.example#b", "a/b/c:c2 com.example#c2", args=["--provides", "::"]
        )

    def test_list_provides_customcols(self):
        self.assert_console_output(
            "/tmp a/b:b http://maven.example.com public com.example#b",
            "/tmp a/b/c:c2 http://maven.example.com public com.example#c2",
            args=[
                "--provides",
                "--provides-columns=push_db_basedir,address,repo_url,repo_name,artifact_id",
                "::",
            ],
        )

    def test_list_dedups(self):
        self.assert_console_output("a/b/c:c3", "a/b/d:d", args=["a/b/d/::", "a/b/c:c3", "a/b/d:d"])

    def test_list_documented(self):
        self.assert_console_output(
            # Confirm empty listing
            args=["--documented", "a/b"],
        )

        self.assert_console_output_ordered(
            "f:alias",
            "  Exercises alias resolution.",
            "  Further description.",
            args=["--documented", "::"],
        )
