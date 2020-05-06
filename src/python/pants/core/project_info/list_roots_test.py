# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.core.project_info import list_roots
from pants.engine.fs import Digest, PathGlobs, Snapshot
from pants.source.source_root import SourceRoot, SourceRootConfig
from pants.testutil.engine.util import MockGet, run_rule
from pants.testutil.goal_rule_test_base import GoalRuleTestBase
from pants.testutil.test_base import TestBase


class AllRootsTest(TestBase):
    def test_all_roots(self):

        options = {
            "pants_ignore": [],
            "source_root_patterns": ["src/*", "src/example/*"],
            "source_roots": {
                # Fixed roots should trump patterns which would detect contrib/go/examples/src/go here.
                "contrib/go/examples/src/go/src": ["go"],
                # Dir does not exist, should not be listed as a root.
                "java": ["java"],
            },
        }
        options.update(self.options[""])  # We need inherited values for pants_workdir etc.

        self.context(
            for_subsystems=[SourceRootConfig], options={SourceRootConfig.options_scope: options}
        )

        source_root_config = SourceRootConfig.global_instance()
        source_roots = source_root_config.get_source_roots()

        # Ensure that we see any manually added roots.
        source_roots.add_source_root("fixed/root/jvm")

        # This function mocks out reading real directories off the file system
        def provider_rule(path_globs: PathGlobs) -> Snapshot:
            dirs = (
                "contrib/go/examples/3rdparty/go",
                "contrib/go/examples/src/go/src",
                "src/java",
                "src/python",
                "src/kotlin",
                "my/project/src/java",
                "src/example/java",
                "src/example/python",
                "fixed/root/jvm",
                # subdirectories of source roots should not show up in final output
                "src/kotlin/additional/directories/that/might/get/matched/src/foo",
            )
            return Snapshot(Digest("abcdef", 10), (), dirs)

        output = run_rule(
            list_roots.all_roots,
            rule_args=[source_root_config],
            mock_gets=[MockGet(product_type=Snapshot, subject_type=PathGlobs, mock=provider_rule)],
        )

        self.assertEqual(
            {
                SourceRoot("contrib/go/examples/3rdparty/go"),
                SourceRoot("contrib/go/examples/src/go/src"),
                SourceRoot("src/java"),
                SourceRoot("src/python"),
                SourceRoot("src/kotlin"),
                SourceRoot("src/example/java"),
                SourceRoot("src/example/python"),
                SourceRoot("my/project/src/java"),
                SourceRoot("fixed/root/jvm"),
            },
            set(output),
        )

    def test_all_roots_with_root_at_buildroot(self):
        options = {
            "pants_ignore": [],
            "source_root_patterns": [],
            "source_roots": {"": ["python"],},
        }
        options.update(self.options[""])  # We need inherited values for pants_workdir etc.

        self.context(
            for_subsystems=[SourceRootConfig], options={SourceRootConfig.options_scope: options}
        )

        source_root_config = SourceRootConfig.global_instance()

        # This function mocks out reading real directories off the file system
        def provider_rule(path_globs: PathGlobs) -> Snapshot:
            dirs = ("foo",)  # A python package at the buildroot.
            return Snapshot(Digest("abcdef", 10), (), dirs)

        output = run_rule(
            list_roots.all_roots,
            rule_args=[source_root_config],
            mock_gets=[MockGet(product_type=Snapshot, subject_type=PathGlobs, mock=provider_rule)],
        )

        self.assertEqual({SourceRoot("")}, set(output))


class RootsTest(GoalRuleTestBase):
    goal_cls = list_roots.Roots

    @classmethod
    def rules(cls):
        return super().rules() + list_roots.rules()

    def test_no_langs_deprecated(self):
        source_roots = json.dumps({"fakeroot": tuple()})
        self.create_dir("fakeroot")
        self.assert_console_output("fakeroot", args=[f"--source-source-roots={source_roots}"])

    def test_single_source_root_deprecated(self):
        source_roots = json.dumps({"fakeroot": ("lang1", "lang2")})
        self.create_dir("fakeroot")
        self.assert_console_output("fakeroot", args=[f"--source-source-roots={source_roots}"])

    def test_multiple_source_roots_deprecated(self):
        source_roots = json.dumps({"fakerootA": ("lang1",), "fakerootB": ("lang2",)})
        self.create_dir("fakerootA")
        self.create_dir("fakerootB")
        self.assert_console_output(
            "fakerootA", "fakerootB", args=[f"--source-source-roots={source_roots}"]
        )

    def test_single_source_root(self):
        source_roots = json.dumps(["fakeroot"])
        self.create_dir("fakeroot")
        self.assert_console_output("fakeroot", args=[f"--source-roots={source_roots}"])

    def test_multiple_source_roots(self):
        self.create_dir("fakerootA")
        self.create_dir("fakerootB")
        source_roots = json.dumps(["fakerootA", "fakerootB"])
        self.assert_console_output(
            "fakerootA", "fakerootB", args=[f"--source-roots={source_roots}"]
        )
