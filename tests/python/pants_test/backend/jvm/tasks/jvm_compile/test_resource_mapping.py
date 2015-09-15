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
    resource_mapping = self._create_mapping('test-data/resource_mapping')

    self.assertEquals(2, len(resource_mapping.mappings))

  def test_resource_mapping_short(self):
    resource_mapping = self._create_mapping('test-data/resource_mapping-broken-short')

    with self.assertRaises(ResourceMapping.TruncatedFileException):
      resource_mapping.mappings

  def test_resource_mapping_long(self):
    resource_mapping = self._create_mapping('test-data/resource_mapping-broken-long')

    with self.assertRaises(ResourceMapping.TooLongFileException):
      resource_mapping.mappings

  def test_resource_mapping_mangled(self):
    resource_mapping = self._create_mapping('test-data/resource_mapping-broken-mangled')

    with self.assertRaises(ResourceMapping.UnparseableLineException):
      resource_mapping.mappings

  def test_resource_mapping_noitems(self):
    resource_mapping = self._create_mapping('test-data/resource_mapping-broken-missing-items')

    with self.assertRaises(ResourceMapping.MissingItemsLineException):
      resource_mapping.mappings

  def _create_mapping(self, rel_path):
    path = os.path.join('tests/python/pants_test/backend/jvm/tasks/jvm_compile', rel_path)
    return ResourceMapping(path)
