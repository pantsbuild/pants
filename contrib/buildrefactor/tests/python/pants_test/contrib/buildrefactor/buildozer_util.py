# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import fnmatch
import os


def clean_build_file(build_file):
  with open(build_file) as f:
    source = f.read()

  new_source = source.replace('u\'', '\'')

  with open(build_file, 'w') as new_file:
    new_file.write(new_source)


def clean_build_directory(path):
  for root, dirs, files in os.walk(path):
    for build_file in fnmatch.filter(files, '*BUILD'):
      clean_build_file('{}/{}'.format(root, build_file))


def assertInFile(self, string, file):
  with open(file) as f:
    source = f.read()

  self.assertIn(string, source)