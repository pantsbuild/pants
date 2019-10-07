# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants_test.base.pants_ignore_test_base import PantsIgnoreTestBase


class FileSystemPantsIgnoreTest(unittest.TestCase, PantsIgnoreTestBase):
    """
  Common test cases are defined in PantsIgnoreTestBase.
  Special test cases can be defined here.
  """

    def mk_project_tree(self, build_root, ignore_patterns=None):
        return FileSystemProjectTree(build_root, ignore_patterns)

    def setUp(self):
        super().setUp()
        self.prepare()

    def tearDown(self):
        super().tearDown()
        self.cleanup()
