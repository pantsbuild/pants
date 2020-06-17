# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os

from pants.backend.project_info import list_roots
from pants.engine.fs import Digest, PathGlobs, Snapshot
from pants.source.source_root import (
    OptionalSourceRoot,
    SourceRoot,
    SourceRootConfig,
    SourceRootRequest,
)
from pants.testutil.engine.util import MockGet, run_rule
from pants.testutil.goal_rule_test_base import GoalRuleTestBase
from pants.testutil.test_base import TestBase


class AllRootsTest(TestBase):
    def test_all_roots(self):

        dirs = (
            "contrib/go/examples/src/go/src",
            "src/java",
            "src/python",
            "src/python/subdir/src/python",  # We allow source roots under source roots.
            "src/kotlin",
            "my/project/src/java",
            "src/example/java",
            "src/example/python",
            "fixed/root/jvm",
        )

        options = {
            "pants_ignore": [],
            "root_patterns": [
                "src/*",
                "src/example/*",
                "contrib/go/examples/src/go/src",
                # Dir does not exist, should not be listed as a root.
                "java",
                "fixed/root/jvm",
            ],
        }
        options.update(self.options[""])  # We need inherited values for pants_workdir etc.

        self.context(
            for_subsystems=[SourceRootConfig], options={SourceRootConfig.options_scope: options}
        )

        source_root_config = SourceRootConfig.global_instance()

        # This function mocks out reading real directories off the file system.
        def provider_rule(path_globs: PathGlobs) -> Snapshot:
            return Snapshot(Digest("abcdef", 10), (), dirs)

        def source_root_mock_rule(req: SourceRootRequest) -> OptionalSourceRoot:
            for d in dirs:
                if str(req.path).startswith(d):
                    return OptionalSourceRoot(SourceRoot(str(req.path)))
            return OptionalSourceRoot(None)

        output = run_rule(
            list_roots.all_roots,
            rule_args=[source_root_config],
            mock_gets=[
                MockGet(product_type=Snapshot, subject_type=PathGlobs, mock=provider_rule),
                MockGet(
                    product_type=OptionalSourceRoot,
                    subject_type=SourceRootRequest,
                    mock=source_root_mock_rule,
                ),
            ],
        )

        self.assertEqual(
            {
                SourceRoot("contrib/go/examples/src/go/src"),
                SourceRoot("src/java"),
                SourceRoot("src/python"),
                SourceRoot("src/python/subdir/src/python"),
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
            "root_patterns": ["/"],
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
            mock_gets=[
                MockGet(product_type=Snapshot, subject_type=PathGlobs, mock=provider_rule),
                MockGet(
                    product_type=OptionalSourceRoot,
                    subject_type=SourceRootRequest,
                    mock=lambda req: OptionalSourceRoot(SourceRoot(".")),
                ),
            ],
        )

        self.assertEqual({SourceRoot(".")}, set(output))


class RootsTest(GoalRuleTestBase):
    goal_cls = list_roots.Roots

    @classmethod
    def rules(cls):
        return [*super().rules(), *list_roots.rules()]

    def test_single_source_root(self):
        source_roots = json.dumps(["fakeroot"])
        self.create_dir("fakeroot")
        self.assert_console_output("fakeroot", args=[f"--source-root-patterns={source_roots}"])

    def test_multiple_source_roots(self):
        self.create_dir("fakerootA")
        self.create_dir("fakerootB")
        source_roots = json.dumps(["fakerootA", "fakerootB"])
        self.assert_console_output(
            "fakerootA", "fakerootB", args=[f"--source-root-patterns={source_roots}"]
        )

    def test_buildroot_is_source_root(self):
        source_roots = json.dumps(["/"])
        self.assert_console_output(".", args=[f"--source-root-patterns={source_roots}"])

    def test_marker_file(self):
        marker_files = json.dumps(["SOURCE_ROOT", "setup.py"])
        self.create_file(os.path.join("fakerootA", "SOURCE_ROOT"))
        self.create_file(os.path.join("fakerootB", "setup.py"))
        self.assert_console_output(
            "fakerootA",
            "fakerootB",
            args=[f"--source-marker-filenames={marker_files}", "--source-root-patterns=[]"],
        )
