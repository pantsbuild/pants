# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest2 as unittest

import bs4
import yaml

from internal_backend.sitegen.tasks import sitegen

CONFIG_YAML = '''
sources:
  index: fake0/README.html
  subdir/page1: fake1/p1.html

tree:
  page: index
  children:
  - page: subdir/page1

# outdir: dist/test_sitegen/ # omit for now...

template: fake/fake.mustache
'''

INDEX_HTML = '''
<h1 id="pants-build-system">Pants Build System</h1>

<p>Pants is a build system.</p>

<p>See also:
<a href="../fake1/p1.html">another page</a>.</p>
'''

P1_HTML = '''
<h1>Page 1</h1>
'''

TEMPLATE_MUSTACHE = '''
{{{body_html}}}
'''


class AllTheThingsTestCase(unittest.TestCase):
  def setUp(self):
    self.config = yaml.load(CONFIG_YAML)
    self.orig_soups = {
      'index': bs4.BeautifulSoup(INDEX_HTML),
      'subdir/page1': bs4.BeautifulSoup(P1_HTML)
    }
    self.precomputed = sitegen.precompute(self.config, self.orig_soups)

  def test_fixup_internal_links(self):
    soups = self.orig_soups.copy()
    sitegen.fixup_internal_links(self.config, soups)
    html = sitegen.render_html('index',
                               self.config,
                               soups,
                               self.precomputed,
                               TEMPLATE_MUSTACHE)
    self.assertTrue('subdir/page1.html' in html,
                    'p1.html link did not get fixed up to page1.html')
