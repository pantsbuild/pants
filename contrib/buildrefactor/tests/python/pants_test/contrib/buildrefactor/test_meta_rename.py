# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.contrib.buildrefactor.buildozer_util import prepare_dependencies
from pants_test.task_test_base import TaskTestBase

from pants.contrib.buildrefactor.meta_rename import MetaRename


class MetaRenameTest(TaskTestBase):
    """Test renaming in MetaRename"""

    @classmethod
    def task_type(cls):
        return MetaRename

    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(targets={"java_library": JavaLibrary})

    def setUp(self):
        super().setUp()

        self.new_name = "goo"
        self.spec_path = "a"
        self.set_options(
            **{
                "from": "{}:a".format(self.spec_path),
                "to": "{}:{}".format(self.spec_path, self.new_name),
            }
        )
        self.meta_rename = self.create_task(
            self.context(target_roots=list(prepare_dependencies(self).values()))
        )

    def test_update_original_build_name(self):
        self.meta_rename.execute()
        self.assertInFile(self.new_name, os.path.join(self.build_root, self.spec_path, "BUILD"))

    def test_update_dependee_references(self):
        self.meta_rename.execute()

        for target in ["a", "b", "c"]:
            self.assertInFile(self.new_name, os.path.join(self.build_root, target, "BUILD"))
