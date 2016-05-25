# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.contrib.go.subsystems.go_import_meta_tag_reader import GoImportMetaTagReader


class FetchersTest(unittest.TestCase):
  def test_find_meta_tag_all_one_line(self):
    test_html = '<!DOCTYPE html><html><head><meta name="go-import" content="google.golang.org/api git https://code.googlesource.com/google-api-go-client"></head><body> Nothing to see here.</body></html>'

    meta_tag_content = GoImportMetaTagReader.find_meta_tag(test_html)
    self.assertEqual(meta_tag_content,
                     ('google.golang.org/api', 'git',
                      'https://code.googlesource.com/google-api-go-client'))

  def test_find_meta_tag_typical(self):
    test_html = """
    <!DOCTYPE html>
    <html>
    <head>
    <meta name="go-import" content="google.golang.org/api git https://code.googlesource.com/google-api-go-client">
    <meta name="go-source" content="google.golang.org/api https://github.com/google/google-api-go-client https://github.com/google/google-api-go-client/tree/master{/dir} https://github.com/google/google-api-go-client/tree/master{/dir}/{file}#L{line}">
    <meta http-equiv="refresh" content="0; url=https://godoc.org/google.golang.org/api/googleapi">
    </head>
    <body>
    Nothing to see here.
    Please <a href="https://godoc.org/google.golang.org/api/googleapi">move along</a>.
    </body>
    </html>
    """

    meta_tag_content = GoImportMetaTagReader.find_meta_tag(test_html)
    self.assertEqual(meta_tag_content,
                     ('google.golang.org/api', 'git',
                      'https://code.googlesource.com/google-api-go-client'))

  def test_find_multiline_meta_tag(self):
    test_html = """
    <!DOCTYPE html>
    <html>
    <head>
    <meta name="go-import"
          content="google.golang.org/api
                   git
                   https://code.googlesource.com/google-api-go-client">
    <meta http-equiv="refresh" content="0; url=https://godoc.org/google.golang.org/api/googleapi">
    </head>
    <body>
    Nothing to see here.
    Please <a href="https://godoc.org/google.golang.org/api/googleapi">move along</a>.
    </body>
    </html>
    """

    meta_tag_content = GoImportMetaTagReader.find_meta_tag(test_html)
    self.assertEqual(meta_tag_content,
                     ('google.golang.org/api', 'git',
                      'https://code.googlesource.com/google-api-go-client'))

  def test_no_meta_tag(self):
    test_html = "<!DOCTYPE html><html><head></head><body>Nothing to see here.</body></html>"

    meta_tag_content = GoImportMetaTagReader.find_meta_tag(test_html)
    self.assertEqual(meta_tag_content, (None, None, None))
