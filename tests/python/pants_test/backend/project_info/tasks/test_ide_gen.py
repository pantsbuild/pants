# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.project_info.tasks.ide_gen import Project, SourceSet
from pants.source.source_root import SourceRootConfig
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import create_subsystem


class IdeGenTest(BaseTest):

  def test_collapse_source_root(self):
    source_roots = create_subsystem(SourceRootConfig, source_roots={
      '/src/java': [],
      '/tests/java': [],
      '/some/other': []
    }, unmatched='fail').get_source_roots()
    source_set_list = []
    self.assertEquals([], Project._collapse_by_source_root(source_roots, source_set_list))

    source_sets = [
      SourceSet('/repo-root', 'src/java', 'org/pantsbuild/app', False),
      SourceSet('/repo-root', 'tests/java', 'org/pantsbuild/app', True),
      SourceSet('/repo-root', 'some/other', 'path', False),
    ]

    results = Project._collapse_by_source_root(source_roots, source_sets)

    self.assertEquals(SourceSet('/repo-root', 'src/java', '', False), results[0])
    self.assertFalse(results[0].is_test)
    self.assertEquals(SourceSet('/repo-root', 'tests/java', '', True), results[1])
    self.assertTrue(results[1].is_test)
    # If there is no registered source root, the SourceSet should be returned unmodified
    self.assertEquals(source_sets[2], results[2])
    self.assertFalse(results[2].is_test)

  def test_source_set(self):
    source_set1 = SourceSet('repo-root', 'path/to/build', 'org/pantsbuild/project', False)
    # only the first 3 parameters are considered keys
    self.assertEquals(('repo-root', 'path/to/build', 'org/pantsbuild/project'),
                      source_set1._key_tuple)
    source_set2 = SourceSet('repo-root', 'path/to/build', 'org/pantsbuild/project', True)
    # Don't consider the test flag
    self.assertEquals(source_set1, source_set2)

  def assert_dedup(self, expected, actual):
    self.assertEquals([expected], actual)
    # that test is not good enough, 'resources_only' and 'is_test' aren't considered keys for the set
    self.assertEquals(expected.resources_only, actual[0].resources_only)
    self.assertEquals(expected.is_test, actual[0].is_test)

  def test_dedup_sources_simple(self):
    self.assertEquals([
      SourceSet('foo', 'bar', ''),
      SourceSet('foo', 'bar', 'baz'),
      SourceSet('foo', 'bar', 'foobar')
    ],
    Project.dedup_sources([
      SourceSet('foo', 'bar', ''),
      SourceSet('foo', 'bar', 'foobar'),
      SourceSet('foo', 'bar', 'baz'),
      SourceSet('foo', 'bar', 'baz'),
      SourceSet('foo', 'bar', 'foobar'),
      SourceSet('foo', 'bar', 'foobar'),
      SourceSet('foo', 'bar', 'baz'),
    ]))

  def test_dedup_sources_resource_and_code(self):
    """Show that a non-resources-only source set turns off the resources_only flag"""
    deduped_sources = Project.dedup_sources([
      SourceSet('foo', 'bar', 'baz', resources_only=True),
      SourceSet('foo', 'bar', 'baz'),
      SourceSet('foo', 'bar', 'baz', resources_only=True),
    ])
    self.assert_dedup(SourceSet('foo', 'bar', 'baz'), deduped_sources)

  def test_dedup_test_sources(self):
    """Show that a is_test on a non resources_only source set turns on is_test"""
    deduped_sources = Project.dedup_sources([
      SourceSet('foo', 'bar', 'baz', is_test=True),
      SourceSet('foo', 'bar', 'baz'),
      SourceSet('foo', 'bar', 'baz', is_test=True),
    ])
    self.assert_dedup(SourceSet('foo', 'bar', 'baz', is_test=True), deduped_sources)

  def test_dedup_test_resources(self):
    """Show that competting is_test values on a resources-only source set turns off is_test"""
    deduped_sources = Project.dedup_sources([
      SourceSet('foo', 'bar', 'baz', is_test=True, resources_only=True),
      SourceSet('foo', 'bar', 'baz', is_test= False, resources_only=True),
      SourceSet('foo', 'bar', 'baz', is_test=True, resources_only=True),
    ])
    self.assert_dedup(SourceSet('foo', 'bar', 'baz', resources_only=True), deduped_sources)

  def test__only_test_resources(self):
    deduped_sources = Project.dedup_sources([
      SourceSet('foo', 'bar', 'baz', is_test=True, resources_only=True),
      SourceSet('foo', 'bar', 'baz', is_test=True, resources_only=True),
    ])
    self.assert_dedup(SourceSet('foo', 'bar', 'baz', is_test=True, resources_only=True),
                      deduped_sources)

  def test_all_together(self):
    deduped_sources = Project.dedup_sources([
      SourceSet('foo', 'bar', 'baz', is_test=True, resources_only=False),
      SourceSet('foo', 'bar', 'baz', is_test=True, resources_only=True),
      SourceSet('foo', 'bar', 'baz', is_test=False, resources_only=True),
      SourceSet('foo', 'bar', 'baz', is_test=False, resources_only=False),
    ])
    self.assert_dedup(SourceSet('foo', 'bar', 'baz', is_test=True), deduped_sources)
