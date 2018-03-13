# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.files import Files
from pants.source.wrapped_globs import Globs
from pants_test.base_test import BaseTest


class FilesTest(BaseTest):
  @staticmethod
  def sources(rel_path, *globs):
    return Globs.create_fileset_with_spec(rel_path, *globs)

  def test_has_sources(self):
    self.create_files('files', ['a.txt', 'B.java'])

    no_files = self.make_target('files:none', Files, sources=self.sources('files', '*.rs'))
    self.assertFalse(no_files.has_sources())
    self.assertFalse(no_files.has_sources('.java'))

    files = self.make_target('files:some', Files, sources=self.sources('files', '*.java'))
    self.assertTrue(files.has_sources())
    self.assertEqual(['files/B.java'], files.sources_relative_to_buildroot())
    self.assertFalse(files.has_sources('.java'))
