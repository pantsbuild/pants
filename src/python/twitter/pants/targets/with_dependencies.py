# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import OrderedSet

from pants.base.target import Target
from pants.targets.util import resolve


class TargetWithDependencies(Target):
  def __init__(self, name, dependencies=None, exclusives=None):
    Target.__init__(self, name, exclusives=exclusives)
    self.dependencies = OrderedSet(resolve(dependencies)) if dependencies else OrderedSet()

  def _walk(self, walked, work, predicate=None):
    Target._walk(self, walked, work, predicate)
    for dependency in self.dependencies:
      for dep in dependency.resolve():
        if isinstance(dep, Target) and not dep in walked:
          walked.add(dep)
          if not predicate or predicate(dep):
            additional_targets = work(dep)
            dep._walk(walked, work, predicate)
            if additional_targets:
              for additional_target in additional_targets:
                if hasattr(additional_target, '_walk'):
                  additional_target._walk(walked, work, predicate)
