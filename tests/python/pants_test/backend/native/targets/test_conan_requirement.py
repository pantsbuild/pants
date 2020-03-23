# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
import unittest

from pants.backend.native.targets.external_native_library import ConanRequirement


class TestConanRequirement(unittest.TestCase):
    def test_parse_conan_stdout_for_pkg_hash(self):
        tc_1 = textwrap.dedent(
            """
            rang/3.1.0@rang/stable: Installing package

            Requirements
                rang/3.1.0@rang/stable from 'pants-conan-remote'
            Packages
                rang/3.1.0@rang/stable:5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9

            rang/3.1.0@rang/stable: Already installed!

            """
        )
        tc_2 = textwrap.dedent(
            """
            rang/3.1.0@rang/stable: Not found, retrieving from server 'pants-conan-remote'
            rang/3.1.0@rang/stable: Trying with 'pants-conan-remote'...
            Downloading conanmanifest.txt

            Downloading conanfile.py

            rang/3.1.0@rang/stable: Installing package
            Requirements
                rang/3.1.0@rang/stable from 'pants-conan-remote'
            Packages
                rang/3.1.0@rang/stable:5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9

            rang/3.1.0@rang/stable: Retrieving package 5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9 from remote 'pants-conan-remote'

            Downloading conanmanifest.txt

            Downloading conaninfo.txt

            Downloading conan_package.tgz

            rang/3.1.0@rang/stable: Package installed 5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9

            """
        )
        pkg_spec = "rang/3.1.0@rang/stable"
        expected_sha = "5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9"
        cr = ConanRequirement(pkg_spec=pkg_spec)
        sha1 = cr.parse_conan_stdout_for_pkg_sha(tc_1)
        self.assertEqual(sha1, expected_sha)
        sha2 = cr.parse_conan_stdout_for_pkg_sha(tc_2)
        self.assertEqual(sha2, expected_sha)

        expected_dir_path = "rang/3.1.0/rang/stable"
        self.assertEqual(expected_dir_path, cr.directory_path)
