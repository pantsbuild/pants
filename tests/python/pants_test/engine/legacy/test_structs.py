# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.engine.legacy.structs import Files


class StructTest(unittest.TestCase):
    def test_filespec_with_excludes(self):
        files = Files(spec_path="")
        self.assertEqual({"globs": []}, files.filespecs)
        files = Files(exclude=["*.md"], spec_path="")
        self.assertEqual({"exclude": [{"globs": ["*.md"]}], "globs": []}, files.filespecs)

    def test_excludes_of_wrong_type(self):
        with self.assertRaises(ValueError) as cm:
            Files(exclude="*.md", spec_path="")
        self.assertEqual('Excludes of type `str` are not supported: got "*.md"', str(cm.exception))
