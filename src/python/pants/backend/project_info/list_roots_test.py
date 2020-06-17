# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os

from pants.backend.project_info import list_roots
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


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
