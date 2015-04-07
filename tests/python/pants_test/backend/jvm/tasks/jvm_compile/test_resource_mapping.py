# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.jvm_compile.resource_mapping import ResourceMapping
from pants_test.base_test import BaseTest


class ResourceMappingTest(BaseTest):
  def test_resource_mapping_ok(self):
    rel_dir = 'tests/python/pants_test/backend/jvm/tasks/jvm_compile/test-data/resource_mapping'
    resource_mapping = ResourceMapping(rel_dir)

    self.assertEquals(2, len(resource_mapping.mappings))

  def test_resource_mapping_short(self):
    rel_dir = 'tests/python/pants_test/backend/jvm/tasks/jvm_compile/test-data/resource_mapping-broken-short'
    resource_mapping = ResourceMapping(rel_dir)

    with self.assertRaises(ResourceMapping.TruncatedFileException):
      resource_mapping.mappings

  def test_resource_mapping_long(self):
    rel_dir = 'tests/python/pants_test/backend/jvm/tasks/jvm_compile/test-data/resource_mapping-broken-long'
    resource_mapping = ResourceMapping(rel_dir)

    with self.assertRaises(ResourceMapping.TooLongFileException):
      resource_mapping.mappings

  def test_resource_mapping_mangled(self):
    rel_dir = 'tests/python/pants_test/backend/jvm/tasks/jvm_compile/test-data/resource_mapping-broken-mangled'
    resource_mapping = ResourceMapping(rel_dir)

    with self.assertRaises(ResourceMapping.UnparseableLineException):
      resource_mapping.mappings


  def test_resource_mapping_noitems(self):
    rel_dir = 'tests/python/pants_test/backend/jvm/tasks/jvm_compile/test-data/resource_mapping-broken-missing-items'
    resource_mapping = ResourceMapping(rel_dir)

    with self.assertRaises(ResourceMapping.MissingItemsLineException):
      resource_mapping.mappings
