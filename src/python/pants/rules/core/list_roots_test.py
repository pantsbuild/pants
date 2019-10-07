# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.engine.fs import Digest, PathGlobs, Snapshot
from pants.rules.core import list_roots
from pants.source.source_root import SourceRoot, SourceRootCategories, SourceRootConfig
from pants_test.console_rule_test_base import ConsoleRuleTestBase
from pants_test.engine.util import run_rule
from pants_test.test_base import TestBase


class AllRootsTest(TestBase):
    def test_all_roots(self):
        SOURCE = SourceRootCategories.SOURCE
        TEST = SourceRootCategories.TEST
        THIRDPARTY = SourceRootCategories.THIRDPARTY

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
        source_roots.add_source_root("fixed/root/jvm", ("java", "scala"), TEST)

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
            list_roots.all_roots, source_root_config, {(Snapshot, PathGlobs): provider_rule}
        )

        self.assertEqual(
            {
                SourceRoot("contrib/go/examples/3rdparty/go", ("go",), THIRDPARTY),
                SourceRoot("contrib/go/examples/src/go/src", ("go",), SOURCE),
                SourceRoot("src/java", ("java",), SOURCE),
                SourceRoot("src/python", ("python",), SOURCE),
                SourceRoot("src/kotlin", ("kotlin",), SOURCE),
                SourceRoot("src/example/java", ("java",), SOURCE),
                SourceRoot("src/example/python", ("python",), SOURCE),
                SourceRoot("my/project/src/java", ("java",), SOURCE),
                SourceRoot("fixed/root/jvm", ("java", "scala"), TEST),
            },
            set(output),
        )


class RootsTest(ConsoleRuleTestBase):
    goal_cls = list_roots.Roots

    @classmethod
    def rules(cls):
        return super().rules() + list_roots.rules()

    def test_no_langs(self):
        source_roots = json.dumps({"fakeroot": tuple()})
        self.create_dir("fakeroot")
        self.assert_console_output("fakeroot: *", args=[f"--source-source-roots={source_roots}"])

    def test_single_source_root(self):
        source_roots = json.dumps({"fakeroot": ("lang1", "lang2")})
        self.create_dir("fakeroot")
        self.assert_console_output(
            "fakeroot: lang1,lang2", args=[f"--source-source-roots={source_roots}"]
        )

    def test_multiple_source_roots(self):
        source_roots = json.dumps({"fakerootA": ("lang1",), "fakerootB": ("lang2",)})
        self.create_dir("fakerootA")
        self.create_dir("fakerootB")
        self.assert_console_output(
            "fakerootA: lang1", "fakerootB: lang2", args=[f"--source-source-roots={source_roots}"]
        )
