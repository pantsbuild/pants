# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import unittest

import bs4
from future.utils import PY3

from internal_backend.sitegen.tasks import sitegen


CONFIG_JSON = """
{
  "sources": {
    "index": "fake0/README.html",
    "subdir/page1": "fake1/p1.html",
    "subdir/page2": "fake1/p2.html",
    "subdir/page2_no_toc": "fake1/p2.html"
  },
  "show_toc": {
    "subdir/page2_no_toc": false
  },
  "extras": {
  },
  "tree": [
    { "page": "index",
      "children": [
        {"heading": "non_collapse"},
        { "pages": ["subdir/page1"] },
        {"collapsible_heading" : "collapse",
          "pages": ["subdir/page2",
                    "index"
                  ]
        }
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
      'index': bs4.BeautifulSoup(INDEX_HTML, 'html.parser'),
      'subdir/page1': bs4.BeautifulSoup(P1_HTML, 'html.parser'),
      'subdir/page2': bs4.BeautifulSoup(P2_HTML, 'html.parser'),
      'subdir/page2_no_toc': bs4.BeautifulSoup(P2_HTML, 'html.parser'),
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

  def test_no_show_toc(self):
    sitegen.generate_page_tocs(self.soups, self.precomputed)
    rendered = sitegen.render_html('subdir/page2_no_toc',
                                   self.config,
                                   self.soups,
                                   self.precomputed,
                                   """
                                   {{#page_toc}}
                                   DEPTH={{depth}} LINK={{link}} TEXT={{text}}
                                   {{/page_toc}}
                                   """)
    self.assertNotIn('DEPTH=1 LINK=one TEXT=Section One', rendered)
    self.assertNotIn('DEPTH=1 LINK=two TEXT=Section Two', rendered)

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
                                   DEPTH={{depth}} LINK={{links}} HEADING={{heading}} 
                                   {{/site_toc}}
                                   """)
    self.assertIn("DEPTH=1 LINK=None HEADING=non_collapse", rendered)
    escaped_single_quote = '&#x27;'
    # Py2 and Py3 order the elements differently and Py3 doesn't render 'u' in unicode literals. Both are valid.
    rendered_expected = ("DEPTH=1 LINK=[{{{q}link{q}: {q}subdir/page2.html{q}, {q}text{q}: {q}Page 2: Electric Boogaloo{q}, {q}here{q}: False}}, "
                         "{{{q}link{q}: {q}index.html{q}, {q}text{q}: {q}Pants Build System{q}, {q}here{q}: True}}] HEADING=collapse".format(q=escaped_single_quote)
                         if PY3 else
                         "DEPTH=1 LINK=[{{{q}text{q}: u{q}Page 2: Electric Boogaloo{q}, {q}link{q}: u{q}subdir/page2.html{q}, {q}here{q}: False}}, "
                         "{{{q}text{q}: u{q}Pants Build System{q}, {q}link{q}: u{q}index.html{q}, {q}here{q}: True}}] HEADING=collapse".format(q=escaped_single_quote))
    self.assertIn(rendered_expected, rendered)

  def test_transform_fixes_up_internal_links(self):
    sitegen.transform_soups(self.config, self.soups, self.precomputed)
    html = sitegen.render_html('index',
                               self.config,
                               self.soups,
                               self.precomputed,
                               TEMPLATE_MUSTACHE)
    self.assertTrue('subdir/page1.html' in html,
                    'p1.html link did not get fixed up to page1.html')
