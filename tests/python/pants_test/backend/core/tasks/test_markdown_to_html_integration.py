# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_open
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class MarkdownIntegrationTest(PantsRunIntegrationTest):
  def test_markdown_normal(self):
    pants_run = self.run_pants(['markdown',
                                'testprojects/src/java/org/pantsbuild/testproject/page:readme'])
    self.assert_success(pants_run)
    out_path = os.path.join(get_buildroot(), 'dist', 'markdown/html',
                            'testprojects/src/java/org/pantsbuild/testproject/page',
                            'README.html')
    with safe_open(out_path) as outfile:
      page_html = outfile.read()
      self.assertIn('../../../../../../../examples/src/java/org/pantsbuild/'
                    'example/hello/main/README.html',
                    page_html,
                    'Failed to resolve [[wiki-like]] pants link.')

  def test_rst_normal(self):
    pants_run = self.run_pants(['markdown',
                                'testprojects/src/java/org/pantsbuild/testproject/page:senserst'])
    self.assert_success(pants_run)
    out_path = os.path.join(get_buildroot(), 'dist', 'markdown/html',
                            'testprojects/src/java/org/pantsbuild/testproject/page',
                            'sense.html')
    with safe_open(out_path) as outfile:
      page_html = outfile.read()
      # should get Sense and Sensibility in title (or TITLE, sheesh):
      self.assertRegexpMatches(page_html,
                               r'(?i).*<title[^>]*>\s*Sense\s+and\s+Sensibility\s*</title')
      # should get formatted with h1:
      self.assertRegexpMatches(page_html,
                               r'(?i).*<h1[^>]*>\s*They\s+Heard\s+Her\s+With\s+Surprise\s*</h1>')
      # should get formatted with _something_
      self.assertRegexpMatches(page_html, r'.*>\s*inhabiting\s*</')
      self.assertRegexpMatches(page_html, r'.*>\s*civilly\s*</')
      # there should be a link that has href="http://www.calderdale.gov.uk/"
      self.assertRegexpMatches(page_html, r'.*<a [^>]*href\s*=\s*[\'"]http://www.calderdale')
