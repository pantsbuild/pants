# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

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
