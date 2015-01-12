# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import re

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_open
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class MarkdownIntegrationTest(PantsRunIntegrationTest):
  def test_markdown_normal(self):
    pants_run = self.run_pants(['markdown',
                                'testprojects/src/java/com/pants/testproject/page:readme'])
    self.assert_success(pants_run)
    out_path = os.path.join(get_buildroot(), 'dist', 'markdown/html',
                            'testprojects/src/java/com/pants/testproject/page',
                            'README.html')
    with safe_open(out_path) as outfile:
      page_html = outfile.read()
      self.assertIn('../../../../../../../examples/src/java/com/pants/'
                    'examples/hello/main/README.html',
                    page_html,
                    'Failed to resolve [[wiki-like]] pants link.')

  def test_rst_normal(self):
    pants_run = self.run_pants(['markdown',
                                'testprojects/src/java/com/pants/testproject/page:senserst'])
    self.assert_success(pants_run)
    out_path = os.path.join(get_buildroot(), 'dist', 'markdown/html',
                            'testprojects/src/java/com/pants/testproject/page',
                            'sense.html')
    with safe_open(out_path) as outfile:
      page_html = outfile.read()
      # should get Sense and Sensibility in title (or TITLE, sheesh):
      assert(re.search(r'<title[^>]*>\s*Sense\s+and\s+Sensibility\s*</title', page_html,
                       re.IGNORECASE))
      # should get formatted with h1:
      assert(re.search(r'<h1[^>]*>\s*They\s+Heard\s+Her\s+With\s+Surprise\s*</h1>', page_html,
                       re.IGNORECASE))
      # should get formatted with _something_
      assert(re.search(r'>\s*inhabiting\s*</', page_html))
      assert(re.search(r'>\s*civilly\s*</', page_html))
      # there should be a link that has href="http://www.calderdale.gov.uk/"
      assert(re.search(r'<a [^>]*href\s*=\s*[\'"]http://www.calderdale', page_html, re.IGNORECASE))
