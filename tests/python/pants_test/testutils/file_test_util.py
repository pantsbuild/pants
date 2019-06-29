# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os


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
  :param iterable expected_files: Set of filepaths relative to directory to search for.
  :param bool ignore_links: Indicates to ignore any file links.
  """

  return sorted(expected_files) == sorted(exact_files(directory, ignore_links=ignore_links))


def check_file_content(path, expected_content):
  """Check file has expected content.

  :API: public

  :param str path: Path to file.
  :param str expected_content: Expected file content.
  """
  with open(path, 'r') as input:
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
