# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest


class FileTestUtilMixin(unittest.TestCase):
  def assert_contains_exact_files(self, directory, expected_files, ignore_links=False):
    """Asserts that the only files which directory contains are expected_files.

    :param str directory: Path to directory to search.
    :param set expected_files: Set of filepaths relative to directory to search for.
    :param bool ignore_links: Indicates to ignore any file links.
    """
    found = []
    for root, _, files in os.walk(directory):
      for f in files:
        p = os.path.join(root, f)
        if ignore_links and os.path.islink(p):
          continue
        found.append(os.path.relpath(p, directory))

    self.assertEqual(sorted(expected_files), sorted(found))

  def assert_file_content(self, path, expected_content):
    """Asserts file is as expected content.

    :param str path: Path to file.
    :param str expected_content: Expected file content.
    """
    with open(path) as input:
      self.assertEquals(expected_content, input.read())

  def assert_symlinks(self, directory, symlinks=True):
    """Asserts files under directory are symlinks.

    :param str directory: Path to directory to search.
    :param bool symlinks: If true, verify files are symlinks, if false, verify files are actual files.
    """
    for root, _, files in os.walk(directory):
      for f in files:
        p = os.path.join(root, f)
        if symlinks ^ os.path.islink(p):
          return False
    return True
