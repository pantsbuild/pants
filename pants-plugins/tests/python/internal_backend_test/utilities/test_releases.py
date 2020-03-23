# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from packaging.version import InvalidVersion, Version

from internal_backend.utilities.register import PantsReleases


def _branch_name(revision_str):
    return PantsReleases._branch_name(Version(revision_str))


class ReleasesTest(unittest.TestCase):
    def test_branch_name_master(self):
        self.assertEqual("master", _branch_name("1.1.0-dev1"))
        self.assertEqual("master", _branch_name("1.1.0dev1"))

    def test_branch_name_stable(self):
        self.assertEqual("1.1.x", _branch_name("1.1.0-rc1"))
        self.assertEqual("1.1.x", _branch_name("1.1.0rc1"))
        self.assertEqual("2.1.x", _branch_name("2.1.0"))
        self.assertEqual("1.2.x", _branch_name("1.2.0rc0-12345"))

        # A negative example: do not prepend `<number>.`, because
        # the first two numbers will be taken as branch name.
        self.assertEqual("12345.1.x", _branch_name("12345.1.2.0rc0"))

    def test_invalid_test_branch_name_stable_append_alphabet(self):
        with self.assertRaises(InvalidVersion):
            _branch_name("1.2.0rc0-abcd")

    def test_invalid_test_branch_name_stable_prepend_numbers(self):
        with self.assertRaises(InvalidVersion):
            _branch_name("12345-1.2.0rc0")

    def test_branch_name_unknown_suffix(self):
        with self.assertRaises(ValueError):
            _branch_name("1.1.0-anything1")
