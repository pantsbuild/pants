# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.util.dirutil import safe_mkdir_for


class ReproMixin(object):
  """ Additional helper methods for use in Repro tests"""

  def add_file(self, root, path, content):
    """Add a file with specified contents

    :param root: (string) Root directory for path.
    :param path: (string) Path relative to root.
    :param content: (string) Content to write to file.
    """
    fullpath = os.path.join(root, path)
    safe_mkdir_for(fullpath)
    with open(fullpath, 'w') as outfile:
      outfile.write(content)

  def assert_not_exists(self, root, path):
    """Assert a file at relpath doesn't exist

    :param root: (string) Root directory of path.
    :param path: (string) Path relative to tar.gz.
    :return: bool
    """
    fullpath = os.path.join(root, path)
    self.assertFalse(os.path.exists(fullpath))

  def assert_file(self, root, path, expected_content=None):
    """ Assert that a file exists with the content specified

    :param root: (string) Root directory of path.
    :param path: (string) Path relative to tar.gz.
    :param expected_content: (string) file contents.
    :return: bool
    """
    fullpath = os.path.join(root, path)
    print(fullpath)
    self.assertTrue(os.path.isfile(fullpath))
    if expected_content:
      with open(fullpath, 'r') as infile:
        content = infile.read()
      self.assertEqual(expected_content, content)
