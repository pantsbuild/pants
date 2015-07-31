# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import unittest

import bs4

from internal_backend.sitegen.tasks import sitegen


CONFIG_JSON = """
{
  "sources": {
    "index": "fake0/README.html",
    "subdir/page1": "fake1/p1.html",
    "subdir/page2": "fake1/p2.html"
  },
  "extras": {
  },
  "tree": [
    { "page": "index",
      "children": [
        { "page": "subdir/page1" },
        { "page": "subdir/page2" }
      ]
    }
  ],
  "template": "fake/fake.mustache"
}
"""

INDEX_HTML = """
<h1 id="pants-build-system">Pants Build System</h1>

<p>Pants is a build system.</p>

<a pantsmark="pantsmark_index"></a>

<p>See also:
<a href="../fake1/p1.html">another page</a>.</p>
"""

P1_HTML = """
<h1>東京 is Tokyo</h1>

<a id="an_pantsmark" pantsmark="pantsmark_p1"></a>

<p>Fascinating description. <a pantsref="pantsmark_index">to index</a>
"""

P2_HTML = """
<head>
  <title>Page 2: Electric Boogaloo</title>
</head>
<body>

<h1>Page 2</h1>

<p>Some text <a pantsref="pantsmark_p1">to p1</a></p>

<h2 id="one">Section One</h2>

<p>Some more text</p>

<h2 id="two">Section Two</h2>

<p>Some more text</p>

</body>
"""

TEMPLATE_MUSTACHE = """
{{{body_html}}}
"""


class AllTheThingsTestCase(unittest.TestCase):

  def setUp(self):
    self.config = json.loads(CONFIG_JSON)
    self.soups = {
      'index': bs4.BeautifulSoup(INDEX_HTML),
      'subdir/page1': bs4.BeautifulSoup(P1_HTML),
      'subdir/page2': bs4.BeautifulSoup(P2_HTML),
    }
    self.precomputed = sitegen.precompute(self.config, self.soups)

  def test_fixup_internal_links(self):
    sitegen.fixup_internal_links(self.config, self.soups)
    html = sitegen.render_html('index',
                               self.config,
                               self.soups,
                               self.precomputed,
                               TEMPLATE_MUSTACHE)
    self.assertIn('subdir/page1.html', html,
                  'p1.html link did not get fixed up to page1.html')

  def test_pantsrefs(self):
    sitegen.link_pantsrefs(self.soups, self.precomputed)
    p1_html = sitegen.render_html('subdir/page1',
                                  self.config,
                                  self.soups,
                                  self.precomputed,
                                  TEMPLATE_MUSTACHE)
    self.assertIn('href="../index.html#pantsmark_index"', p1_html,
                  'pantsref_index did not get linked')
    p2_html = sitegen.render_html('subdir/page2',
                                  self.config,
                                  self.soups,
                                  self.precomputed,
                                  TEMPLATE_MUSTACHE)
    self.assertIn('href="page1.html#an_pantsmark"', p2_html,
                  'pantsref_p1 did not get linked')

  def test_find_title(self):
    p2_html = sitegen.render_html('subdir/page2',
                                  self.config,
                                  self.soups,
                                  self.precomputed,
                                  '{{title}}')
    self.assertEqual(p2_html, 'Page 2: Electric Boogaloo',
                     """Didn't find correct title""")
    # ascii worked? great, try non-ASCII
    p1_html = sitegen.render_html('subdir/page1',
                                  self.config,
                                  self.soups,
                                  self.precomputed,
                                  '{{title}}')
    self.assertEqual(p1_html, u'東京 is Tokyo',
                     """Didn't find correct non-ASCII title""")

  def test_page_toc(self):
    # One of our "pages" has a couple of basic headings.
    # Do we get the correct info from that to generate
    # a page-level table of contents?
    sitegen.generate_page_tocs(self.soups, self.precomputed)
    rendered = sitegen.render_html('subdir/page2',
                                   self.config,
                                   self.soups,
                                   self.precomputed,
                                   """
                                   {{#page_toc}}
                                   DEPTH={{depth}} LINK={{link}} TEXT={{text}}
                                   {{/page_toc}}
                                   """)
    self.assertIn('DEPTH=1 LINK=one TEXT=Section One', rendered)
    self.assertIn('DEPTH=1 LINK=two TEXT=Section Two', rendered)

  def test_transforms_not_discard_page_tocs(self):
    # We had a bug where one step of transform lost the info
    # we need to build page-tocs. Make sure that doesn't happen again.
    sitegen.transform_soups(self.config, self.soups, self.precomputed)
    rendered = sitegen.render_html('subdir/page2',
                                   self.config,
                                   self.soups,
                                   self.precomputed,
                                   """
                                   {{#page_toc}}
                                   DEPTH={{depth}} LINK={{link}} TEXT={{text}}
                                   {{/page_toc}}
                                   """)
    self.assertIn('DEPTH=1 LINK=one TEXT=Section One', rendered)
    self.assertIn('DEPTH=1 LINK=two TEXT=Section Two', rendered)

  def test_here_links(self):
    sitegen.add_here_links(self.soups)
    html = sitegen.render_html('index',
                               self.config,
                               self.soups,
                               self.precomputed,
                               TEMPLATE_MUSTACHE)
    self.assertIn('href="#pants-build-system"', html,
                  'Generated html lacks auto-created link to h1.')

  def test_breadcrumbs(self):
    # Our "site" has a simple outline.
    # Do we get the correct info from that to generate
    # "breadcrumbs" navigating from one page up to the top?
    rendered = sitegen.render_html('subdir/page2',
                                   self.config,
                                   self.soups,
                                   self.precomputed,
                                   """
                                   {{#breadcrumbs}}
                                   LINK={{link}} TEXT={{text}}
                                   {{/breadcrumbs}}
                                   """)
    self.assertIn('LINK=../index.html TEXT=Pants Build System', rendered)

  def test_site_toc(self):
    # Our "site" has a simple outline.
    # Do we get the correct info from that to generate
    # a site-level table of contents?
    rendered = sitegen.render_html('index',
                                   self.config,
                                   self.soups,
                                   self.precomputed,
                                   """
                                   {{#site_toc}}
                                   DEPTH={{depth}} LINK={{link}} TEXT={{text}}
                                   {{/site_toc}}
                                   """)
    self.assertIn(u'DEPTH=1 LINK=subdir/page1.html TEXT=東京 is Tokyo', rendered)
    self.assertIn('DEPTH=1 LINK=subdir/page2.html TEXT=Page 2: Electric Boogaloo', rendered)

  def test_transform_fixes_up_internal_links(self):
    sitegen.transform_soups(self.config, self.soups, self.precomputed)
    html = sitegen.render_html('index',
                               self.config,
                               self.soups,
                               self.precomputed,
                               TEMPLATE_MUSTACHE)
    self.assertTrue('subdir/page1.html' in html,
                    'p1.html link did not get fixed up to page1.html')
