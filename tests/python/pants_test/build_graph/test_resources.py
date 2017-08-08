# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.resources import Resources
from pants.source.wrapped_globs import Globs
from pants_test.base_test import BaseTest


class ResourcesTest(BaseTest):
  @staticmethod
  def sources(rel_path, *globs):
    return Globs.create_fileset_with_spec(rel_path, *globs)

  def test_has_sources(self):
    self.create_files('resources', ['a.txt', 'B.java'])

    no_resources = self.make_target('resources:none',
                                    Resources,
                                    sources=self.sources('resources', '*.rs'))
    self.assertFalse(no_resources.has_sources())
    self.assertFalse(no_resources.has_sources('.java'))

    resources = self.make_target('resources:some',
                                 Resources,
                                 sources=self.sources('resources', '*.java'))
    self.assertTrue(resources.has_sources())
    self.assertEqual(['resources/B.java'], resources.sources_relative_to_buildroot())
    self.assertFalse(resources.has_sources('.java'))
