# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.fs.archive import ZIP
from pants.util.contextutil import temporary_dir


def exact_files(directory, ignore_links=False):
  """Returns the relative files contained in the directory.

  :API: public

  :param str directory: Path to directory to search.
  :param bool ignore_links: Indicates to ignore any file links.
  """
  found = []
  for root, _, files in os.walk(directory, followlinks=not ignore_links):
    for f in files:
      p = os.path.join(root, f)
      if ignore_links and os.path.islink(p):
        continue
      found.append(os.path.relpath(p, directory))

  return found


def contains_exact_files(directory, expected_files, ignore_links=False):
  """Check if the only files which directory contains are expected_files.

  :API: public

  :param str directory: Path to directory to search.
  :param set expected_files: Set of filepaths relative to directory to search for.
  :param bool ignore_links: Indicates to ignore any file links.
  """

  return sorted(expected_files) == sorted(exact_files(directory, ignore_links=ignore_links))


def check_file_content(path, expected_content):
  """Check file has expected content.

  :API: public

  :param str path: Path to file.
  :param str expected_content: Expected file content.
  """
  with open(path) as input:
    return expected_content == input.read()


def check_symlinks(directory, symlinks=True):
  """Check files under directory are symlinks.

  :API: public

  :param str directory: Path to directory to search.
  :param bool symlinks: If true, verify files are symlinks, if false, verify files are actual files.
  """
  for root, _, files in os.walk(directory):
    for f in files:
      p = os.path.join(root, f)
      if symlinks ^ os.path.islink(p):
        return False
  return True


def check_zip_file_content(zip_file, expected_files):
  """Check zip file contains expected files as well as verify their contents are as expected.

  :API: public

  :param zip_file: Path to the zip file.
  :param expected_files: A map from file path included in the zip to its content. Set content
    to `None` to skip checking.
  :return:
  """
  with temporary_dir() as workdir:
    ZIP.extract(zip_file, workdir)
    if not contains_exact_files(workdir, expected_files.keys()):
      return False

    for rel_path in expected_files:
      path = os.path.join(workdir, rel_path)
      if expected_files[rel_path] and not check_file_content(path, expected_files[rel_path]):
        return False

  return True
