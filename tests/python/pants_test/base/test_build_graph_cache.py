# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.address import Address
from pants.base.build_file import FilesystemBuildFile
from pants.base.build_graph_cache import BuildGraphCache
from pants_test.base_test import BaseTest


class BuildGraphCacheTest(BaseTest):

  def setUp(self):
    super(BuildGraphCacheTest, self).setUp()
    self.build_graph_cache = BuildGraphCache(self.build_root, self.address_mapper._build_file_type,
                                        self.address_mapper, self.build_graph)

  def test_empty_reinsert_does_not_fail(self):
    self.create_file('some/path/BUILD', '', mode='w')

    build_file_path = self.build_path('some/path/BUILD')
    build_file = FilesystemBuildFile(self.build_root, build_file_path)

    self.build_graph_cache.reparse_build_file(build_file)

  def add_target_and_reinsert(self, spec_path, build_file_path):
    build_file_path = self.build_path(build_file_path)
    self.create_file(build_file_path,
                     'target(name = "util_cpp")\n'
                     'target(name = "util_java")\n',
                     mode='w')
    build_file = FilesystemBuildFile(self.build_root, build_file_path)

    self.build_graph_cache.reparse_build_file(build_file)

    self.assertIn(Address.parse(spec_path + ':util_cpp'), self.build_graph._target_by_address)
    self.assertIn(Address.parse(spec_path + ':util_java'), self.build_graph._target_by_address)

    self.create_file(build_file_path,
                     'target(name = "util_cpp")\n'
                     'target(name = "util_java")\n'
                     'target(name = "util_scala")\n',
                     mode='w')
    self.build_graph_cache.reparse_build_file(build_file)

    self.assertIn(Address.parse(spec_path + ':util_cpp'), self.build_graph._target_by_address)
    self.assertIn(Address.parse(spec_path + ':util_java'), self.build_graph._target_by_address)
    self.assertIn(Address.parse(spec_path + ':util_scala'), self.build_graph._target_by_address)

  def remove_target_and_reinsert(self, spec_path, build_file_path):
    build_file_path = self.build_path(build_file_path)
    self.create_file(build_file_path,
                     'target(name = "util_cpp")\n'
                     'target(name = "util_java")\n',
                     mode='w')
    build_file = FilesystemBuildFile(self.build_root, build_file_path)

    self.build_graph_cache.reparse_build_file(build_file)

    self.assertIn(Address.parse(spec_path + ':util_cpp'), self.build_graph._target_by_address)
    self.assertIn(Address.parse(spec_path + ':util_java'), self.build_graph._target_by_address)

    self.create_file(build_file_path,
                     'target(name = "util_cpp")\n',
                     mode='w')
    self.build_graph_cache.reparse_build_file(build_file)

    self.assertIn(Address.parse(spec_path + ':util_cpp'), self.build_graph._target_by_address)
    self.assertNotIn(Address.parse(spec_path + ':util_java'), self.build_graph._target_by_address)

  def test_reinsert_adds_target(self):
    self.add_target_and_reinsert('//', 'BUILD')
    self.add_target_and_reinsert('some/path', 'some/path/BUILD')

  def test_reinsert_removes_target(self):
    self.remove_target_and_reinsert('//', 'BUILD')
    self.remove_target_and_reinsert('some/path', 'some/path/BUILD')
