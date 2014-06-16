# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.lang import Compatibility

if Compatibility.PY3:
  import unittest
else:
  import unittest2 as unittest

from pants.base.build_environment import get_buildroot


class Utf8HeaderTest(unittest.TestCase):

  def test_file_have_coding_utf8(self):
    """
    Look through all .py files and ensure they start with the line '# coding=utf8'
    """
    buildroot = get_buildroot();

    nonconforming_files = []
    for root, dirs, files in os.walk(buildroot):
      # build-support contains a lot of external files.
      if root.find(os.sep + "build-support") >= 0:
        continue
      for filename in files:
        if filename.endswith(".py"):
          path = root + os.sep + filename;
          with open(path, "r") as pyFile:
            firstLine = pyFile.readline()
            if not firstLine.rstrip() == "# coding=utf-8":
              nonconforming_files.append(path)

    if len(nonconforming_files) > 0:
      self.fail('Expected these files to contain first line "# coding=utf8": ' + str(nonconforming_files))
