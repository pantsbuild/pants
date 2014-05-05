# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.config import Config
from pants.goal import Context
from pants_test.base_test import BaseTest


class ContextTest(BaseTest):
  def create_context(self, **kwargs):
    return Context(self.config,
                   build_graph=self.build_graph,
                   build_file_parser=self.build_file_parser,
                   run_tracker=None,
                   **kwargs)

  def test_dependents_empty(self):
    context = self.create_context(options={}, target_roots=[])
    dependees = context.dependents()
    self.assertEquals(0, len(dependees))

  def test_dependents_direct(self):
    a = self.make_target('a')
    b = self.make_target('b', dependencies=[a])
    c = self.make_target('c', dependencies=[b])
    d = self.make_target('d', dependencies=[c, a])
    e = self.make_target('e', dependencies=[d])
    context = self.create_context(options={}, target_roots=[a, b, c, d, e])
    dependees = context.dependents(lambda t: t in set([e, c]))
    self.assertEquals(set([c]), dependees.pop(d))
    self.assertEquals(0, len(dependees))
