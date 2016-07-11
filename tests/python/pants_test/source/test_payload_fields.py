# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.source.payload_fields import SourcesField
from pants.source.wrapped_globs import EagerFilesetWithSpec, Globs, LazyFilesetWithSpec
from pants_test.base_test import BaseTest


class PayloadTest(BaseTest):
  def sources(self, rel_path, *args):
    return Globs.create_fileset_with_spec(rel_path, *args)

  def test_sources_field(self):
    self.create_file('foo/bar/a.txt', 'a_contents')
    self.create_file('foo/bar/b.txt', 'b_contents')

    self.assertNotEqual(
      SourcesField(
        sources=self.sources('foo/bar', 'a.txt'),
      ).fingerprint(),
      SourcesField(
        sources=self.sources('foo/bar', 'b.txt'),
      ).fingerprint(),
    )

    self.assertEqual(
      SourcesField(
        sources=self.sources('foo/bar', 'a.txt'),
      ).fingerprint(),
      SourcesField(
        sources=self.sources('foo/bar', 'a.txt'),
      ).fingerprint(),
    )

    self.assertEqual(
      SourcesField(
        sources=self.sources('foo/bar', 'a.txt', 'b.txt'),
      ).fingerprint(),
      SourcesField(
        sources=self.sources('foo/bar', 'a.txt', 'b.txt'),
      ).fingerprint(),
    )

    fp1 = SourcesField(
            sources=self.sources('foo/bar', 'a.txt'),
          ).fingerprint()
    self.create_file('foo/bar/a.txt', 'a_contents_different')
    fp2 = SourcesField(
            sources=self.sources('foo/bar', 'a.txt'),
          ).fingerprint()

    self.assertNotEqual(fp1, fp2)

  def test_fails_on_invalid_sources_kwarg(self):
    with self.assertRaises(ValueError):
      SourcesField(sources='not-a-list')

  def test_passes_lazy_fileset_with_spec_through(self):
    self.create_file('foo/a.txt', 'a_contents')

    fileset = LazyFilesetWithSpec('foo', 'a.txt', lambda: ['a.txt'])
    sf = SourcesField(sources=fileset)

    self.assertIs(fileset, sf.sources)
    self.assertEqual(['a.txt'], list(sf.source_paths))

  def test_passes_eager_fileset_with_spec_through(self):
    self.create_file('foo/a.txt', 'a_contents')

    fileset = EagerFilesetWithSpec('foo', {'globs': 'a.txt'}, ['a.txt'], {'a.txt': b'12345'})
    sf = SourcesField(sources=fileset)

    self.assertIs(fileset, sf.sources)
    self.assertEqual(['a.txt'], list(sf.source_paths))
