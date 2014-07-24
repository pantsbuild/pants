# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.register import build_file_aliases as register_core
from pants_test.base_test import BaseTest

CONFLUENCE_SETUP_SNIPPET="""
confluence = "fake"

# literalinclude this part in doc:

class OurConfluence(ConfluencePublish):
  def wiki(self):
    return confluence # wiki target defined above
  def api(self):
    return 'confluence2' # Older confluence installations use older API

goal(
  name='confluence',
  action=OurConfluence,
  dependencies=['markdown']
).install().with_description('Publish one or more confluence pages.')

# stop including in doc
"""

class SetupConfluenceTest(BaseTest):
  @property
  def alias_groups(self):
    return register_core()

  def test_confluence_setup_parses(self):
    self.add_to_build_file('BUILD', CONFLUENCE_SETUP_SNIPPET)
    self.build_file_parser.scan(self.build_root)
