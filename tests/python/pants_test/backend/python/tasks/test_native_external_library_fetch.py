# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import textwrap
import unittest

from pants.backend.native.tasks.native_external_library_fetch import (ConanRequirement,
                                                                      NativeExternalLibraryFetch)
from pants.util.osutil import get_normalized_os_name


class TestConanRequirement(unittest.TestCase):

  def test_parse_conan_stdout_for_pkg_hash(self):
    tc_1 = textwrap.dedent("""
      rang/3.1.0@rang/stable: Installing package\n
      Requirements\n    rang/3.1.0@rang/stable from 'pants-conan-remote'
      \nPackages\n    rang/3.1.0@rang/stable:5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9\n\n
      rang/3.1.0@rang/stable: Already installed!\n"
    """
    )
    tc_2 = textwrap.dedent(
      "rang/3.1.0@rang/stable: Not found, retrieving from server 'pants-conan-remote' \n"
      "rang/3.1.0@rang/stable: Trying with 'pants-conan-remote'...\nDownloading conanmanifest.txt\n"
      "\nDownloading conanfile.py\n\nrang/3.1.0@rang/stable: Installing package\nRequirements\n    "
      "rang/3.1.0@rang/stable from 'pants-conan-remote'\nPackages\n    "
      "rang/3.1.0@rang/stable:5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9\n\nrang/3.1.0@rang/stable: "
      "Retrieving package 5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9 from remote 'pants-conan-remote' \n"
      "Downloading conanmanifest.txt\n\nDownloading conaninfo.txt\n\nDownloading conan_package.tgz\n\n"
      "rang/3.1.0@rang/stable: Package installed 5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9\n"
    )
    pkg_spec = 'rang/3.1.0@rang/stable'
    expected_sha = '5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9'
    cr = ConanRequirement.parse(pkg_spec)
    sha1 = cr.parse_conan_stdout_for_pkg_sha(tc_1)
    self.assertEqual(sha1, expected_sha)
    sha2 = cr.parse_conan_stdout_for_pkg_sha(tc_2)
    self.assertEqual(sha2, expected_sha)

  def test_build_conan_cmdline_args(self):
    pkg_spec = 'test/1.0.0@conan/stable'
    cr = ConanRequirement.parse(pkg_spec)
    cmdline = cr._build_conan_cmdline_args(pkg_spec)
    os_name = get_normalized_os_name()
    if os_name == 'linux':
      expected = ['install', 'test/1.0.0@conan/stable', '-s', 'os=Linux']
    elif os_name == 'darwin':
      expected = ['install', 'test/1.0.0@conan/stable', '-s', 'os=Macos']
    else:
      expected = 'Unsupported platform'
    self.assertEqual(cmdline, expected)


class TestNativeExternalLibraryFetch(unittest.TestCase):

  def test_parse_lib_name_from_library_filename(self):
    tc_1 = 'liblzo.a'
    tc_2 = 'libtensorflow.so'
    tc_3 = 'libz.dylib'
    tc_4 = 'libbadextension.lol'
    tc_5 = 'badfilename.so'
    res = NativeExternalLibraryFetch._parse_lib_name_from_library_filename(tc_1)
    self.assertEqual(res, 'lzo')
    res = NativeExternalLibraryFetch._parse_lib_name_from_library_filename(tc_2)
    self.assertEqual(res, 'tensorflow')
    res = NativeExternalLibraryFetch._parse_lib_name_from_library_filename(tc_3)
    self.assertEqual(res, 'z')
    res = NativeExternalLibraryFetch._parse_lib_name_from_library_filename(tc_4)
    self.assertEqual(res, None)
    res = NativeExternalLibraryFetch._parse_lib_name_from_library_filename(tc_5)
    self.assertEqual(res, None)
