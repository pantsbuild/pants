# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from textwrap import dedent

import pytest

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.scala_artifact import ScalaArtifact
from pants.backend.jvm.target_types import JavaLibrary
from pants.backend.python.target_types import PythonLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.project_info import list_targets
from pants.core.target_types import GenericTarget
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class ListTargetsTest(GoalRuleTestBase):
    goal_cls = list_targets.List

    @classmethod
    def target_types(cls):
        return [
            GenericTarget,
            JavaLibrary,
            PythonLibrary,
        ]

    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(
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
        #   tests/python/pants_test/integration/list_integration_test.py
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

    @pytest.mark.skip(reason="flaky: https://github.com/pantsbuild/pants/issues/8678")
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
            args=["--sep=, ", "::"],
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
            "a/b:b com.example#b", "a/b/c:c2 com.example#c2", args=["--output-format=provides", "::"]
        )

    def test_list_provides_customcols(self):
        self.assert_console_output(
            "/tmp a/b:b http://maven.example.com public com.example#b",
            "/tmp a/b/c:c2 http://maven.example.com public com.example#c2",
            args=[
                "--output-format=provides",
                "--provides-columns=push_db_basedir,address,repo_url,repo_name,artifact_id",
                "::",
            ],
        )

    def test_list_dedups(self):
        self.assert_console_output("a/b/c:c3", "a/b/d:d", args=["a/b/d/::", "a/b/c:c3", "a/b/d:d"])

    def test_list_documented(self):
        self.assert_console_output(
            # Confirm empty listing
            args=["--output-format=documented", "a/b"],
        )

        self.assert_console_output_ordered(
            "f:alias",
            "  Exercises alias resolution.",
            "  Further description.",
            args=["--output-format=documented", "::"],
        )

    def _list_json(self, targets):
        return [
            json.loads(target_info)
            for target_info in self.execute_rule(
                args=["--output-format=json", *targets],
            ).stdout.splitlines()
        ]

    def test_list_json(self):

        f_alias, c3, d = tuple(self._list_json(["f:alias"]))

        assert f_alias["address"] == "f:alias"
        assert f_alias["target_type"] == "target"

        assert c3["address"] == "a/b/c:c3"
        assert c3["target_type"] == "java_library"

        assert d["address"] == "a/b/d:d"
        assert d["target_type"] == "java_library"

    def test_list_json_distinct(self):
        """Test that modifying sources will change the recorded fingerprints."""
        self.create_file("g/Test.java", contents="")
        self.add_to_build_file(
            "g",
            dedent(
                """\
        java_library(
            name="a",
            sources=["Test.java"],
        )
        java_library(
            name="b",
            sources=["Test.java"],
        )
        target(
            name="c",
            dependencies=[":b"],
        )
        """
            ),
        )

        g_a_0, g_b_0, g_c_0 = tuple(self._list_json(["g:a", "g:b", "g:c"]))

        # Modify the source file and see that the fingerprints have changed.
        self.create_file("g/Test.java", contents="\n\n\n")

        g_a_1, g_b_1, g_c_1 = tuple(self._list_json(["g:a", "g:b", "g:c"]))

        # Modified, because sources were changed.
        assert g_a_0["intransitive_fingerprint"] != g_a_1["intransitive_fingerprint"]
        assert g_a_0["transitive_fingerprint"] != g_a_1["transitive_fingerprint"]

        # Modified, because sources were changed.
        assert g_b_0["intransitive_fingerprint"] != g_b_1["intransitive_fingerprint"]
        assert g_b_0["transitive_fingerprint"] != g_b_1["transitive_fingerprint"]

        # Unchanged.
        assert g_c_0["intransitive_fingerprint"] == g_c_1["intransitive_fingerprint"]
        # Modified, because sources of the dependency g:b were changed.
        assert g_c_0["transitive_fingerprint"] != g_c_1["transitive_fingerprint"]
