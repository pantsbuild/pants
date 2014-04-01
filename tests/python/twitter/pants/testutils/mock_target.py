# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict

from pants.base.parse_context import ParseContext
from pants.targets.internal import InternalTarget
from pants.targets.with_sources import TargetWithSources


class MockTarget(InternalTarget, TargetWithSources):
  def __init__(self, name, dependencies=None, num_sources=0, exclusives=None):
    with ParseContext.temp():
      InternalTarget.__init__(self, name, dependencies, exclusives=exclusives)
      TargetWithSources.__init__(self, name, exclusives=exclusives)
    self.num_sources = num_sources
    self.declared_exclusives = defaultdict(set)
    if exclusives is not None:
      for k in exclusives:
        self.declared_exclusives[k] = set([exclusives[k]])
    self.exclusives = None

  def resolve(self):
    yield self

  def walk(self, work, predicate=None):
    work(self)
    for dep in self.dependencies:
      dep.walk(work)
