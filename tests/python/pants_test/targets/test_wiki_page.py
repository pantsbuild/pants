# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.core.targets.doc import Page, Wiki, WikiArtifact
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.build_file_aliases import BuildFileAliases
from pants_test.base_test import BaseTest


class WikiPageTest(BaseTest):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(
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

    self.add_to_build_file('root', dedent("""
        source_root('junk/docs', page)
      """))

    self.add_to_build_file('junk/docs', dedent("""

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
          source='README2.md',
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

    self.create_file('junk/docs/README.md', contents=dedent("""
some text

* [[Link to the other readme file|pants('junk/docs:readme2')]]

some text

* [[Link AGAIN to the other readme file|pants('junk/docs:readme2')]]

    """))

    self.create_file('junk/docs/README2.md', contents=dedent("""
This is the second readme file! Isn't it exciting?

[[link to the first readme file|pants('junk/docs:readme')]]
    """))

  def test_wiki_page(self):
    p = self.target('junk/docs:readme')

    self.assertIsInstance(p, Page)
    self.assertIsInstance(p.provides[0], WikiArtifact)
    self.assertIsInstance(p.provides[0].wiki, Wiki)
    self.assertTrue(isinstance(p, Page), "%s isn't an instance of Page" % p)
    self.assertTrue(isinstance(p.provides[0], WikiArtifact), "%s isn't an instance of WikiArtifact" % p)
    self.assertTrue(isinstance(p.provides[0].wiki, Wiki), "%s isn't an instance of Wiki" % p)
    self.assertEquals("~areitz", p.provides[0].config['space'])
    self.assertEquals("test_page", p.provides[0].config['title'])
    self.assertFalse('parent' in p.provides[0].config)

    # Check to make sure the 'readme2' target has been loaded into the build graph (via parsing of
    # the 'README.md' page)
    address = SyntheticAddress.parse('junk/docs:readme2', relative_to=get_buildroot())
    self.assertEquals(p._build_graph.get_target(address), self.target('junk/docs:readme2'))
