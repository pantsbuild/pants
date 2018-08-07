# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from textwrap import dedent

from pants.backend.docgen.targets.doc import Page, Wiki, WikiArtifact
from pants.base.build_environment import get_buildroot
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.test_base import TestBase


class WikiPageTest(TestBase):

  @classmethod
  def alias_groups(cls):
    return BuildFileAliases(
      targets={
        'page': Page,
      },
      objects={
        'Wiki': Wiki,
        'wiki_artifact': WikiArtifact,
        'confluence': Wiki(name='confluence_wiki', url_builder=None),
      },
    )

  def setUp(self):
    super(WikiPageTest, self).setUp()

    self.add_to_build_file('src/docs', dedent("""

        page(name='readme',
          source='README.md',
          links=[':readme2'],
          provides=[
            wiki_artifact(
              wiki=confluence,
              space='~areitz',
              title='test_page',
            ),
          ],
        )

        page(name='readme2',
          sources=['README2.md'],
          links=[':readme'],
          provides=[
            wiki_artifact(
              wiki=confluence,
              space='~areitz',
              title='test_page2',
            ),
          ],
        )
    """))

    self.create_file('src/docs/README.md', contents=dedent("""
some text

* [[Link to the other readme file|pants('src/docs:readme2')]]

some text

* [[Link AGAIN to the other readme file|pants('src/docs:readme2')]]

    """))

    self.create_file('src/docs/README2.md', contents=dedent("""
This is the second readme file! Isn't it exciting?

[[link to the first readme file|pants('src/docs:readme')]]
    """))

  def test_wiki_page(self):
    p = self.target('src/docs:readme')

    self.assertIsInstance(p, Page)
    self.assertIsInstance(p.provides[0], WikiArtifact)
    self.assertIsInstance(p.provides[0].wiki, Wiki)
    self.assertTrue(isinstance(p, Page), "%s isn't an instance of Page" % p)
    self.assertTrue(isinstance(p.provides[0], WikiArtifact), "%s isn't an instance of WikiArtifact" % p)
    self.assertTrue(isinstance(p.provides[0].wiki, Wiki), "%s isn't an instance of Wiki" % p)
    self.assertEqual("~areitz", p.provides[0].config['space'])
    self.assertEqual("test_page", p.provides[0].config['title'])
    self.assertFalse('parent' in p.provides[0].config)

    # Check to make sure the 'readme2' target has been loaded into the build graph (via parsing of
    # the 'README.md' page)
    address = Address.parse('src/docs:readme2', relative_to=get_buildroot())
    self.assertEqual(p._build_graph.get_target(address), self.target('src/docs:readme2'))

  def test_wiki_page_fingerprinting(self):
    def create_page_target(space):
      self.reset_build_graph()
      self.create_file('src/docs/BUILD')
      self.add_to_build_file('src/docs', dedent("""
        page(name='readme3',
          source='README.md',
          provides=[
            wiki_artifact(
              wiki=confluence,
              space='~""" + space + """',
              title='test_page3',
            ),
          ],
        )
      """))
      return self.target('src/docs:readme3')

    fingerprint_before = create_page_target('space1').payload.fingerprint()
    self.assertEqual(fingerprint_before, create_page_target('space1').payload.fingerprint())
    self.assertNotEqual(fingerprint_before, create_page_target('space2').payload.fingerprint())

  def test_no_sources(self):
    self.add_to_build_file('', "page(name='page', sources=['does-not-exist.md'])")
    with self.assertRaisesRegexp(AddressLookupError, r'//:page.*exactly 1 source, but found 0'):
      self.target(':page')

  def test_multiple_sources(self):
    self.create_files('', ['exists.md', 'also-exists.md'])
    self.add_to_build_file('', "page(name='page', sources=['exists.md', 'also-exists.md'])")
    with self.assertRaisesRegexp(AddressLookupError, r'//:page.*exactly 1 source, but found 2'):
      self.target(':page')

  def test_source_and_sources(self):
    self.create_files('', ['exists.md', 'also-exists.md'])
    self.add_to_build_file(
      '',
      "page(name='page', source=['exists.md'], sources=['also-exists.md'])",
    )
    with self.assertRaisesRegexp(
      AddressLookupError,
      r'//:page: Cannot specify both source and sources attribute'
    ):
      self.target(':page')
