# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.source.payload_fields import SourcesField
from pants_test.base_test import BaseTest


class PayloadTest(BaseTest):
  def test_sources_field(self):
    self.create_file('foo/bar/a.txt', 'a_contents')
    self.create_file('foo/bar/b.txt', 'b_contents')

    self.assertNotEqual(
      SourcesField(
        sources_rel_path='foo/bar',
        sources=['a.txt'],
      ).fingerprint(),
      SourcesField(
        sources_rel_path='foo/bar',
        sources=['b.txt'],
      ).fingerprint(),
    )

    self.assertEqual(
      SourcesField(
        sources_rel_path='foo/bar',
        sources=['a.txt'],
      ).fingerprint(),
      SourcesField(
        sources_rel_path='foo/bar',
        sources=['a.txt'],
      ).fingerprint(),
    )

    self.assertEqual(
      SourcesField(
        sources_rel_path='foo/bar',
        sources=['a.txt'],
      ).fingerprint(),
      SourcesField(
        sources_rel_path='foo/bar',
        sources=['a.txt'],
      ).fingerprint(),
    )

    self.assertEqual(
      SourcesField(
        sources_rel_path='foo/bar',
        sources=['a.txt', 'b.txt'],
      ).fingerprint(),
      SourcesField(
        sources_rel_path='foo/bar',
        sources=['b.txt', 'a.txt'],
      ).fingerprint(),
    )

    fp1 = SourcesField(
            sources_rel_path='foo/bar',
            sources=['a.txt'],
          ).fingerprint()
    self.create_file('foo/bar/a.txt', 'a_contents_different')
    fp2 = SourcesField(
            sources_rel_path='foo/bar',
            sources=['a.txt'],
          ).fingerprint()

    self.assertNotEqual(fp1, fp2)
