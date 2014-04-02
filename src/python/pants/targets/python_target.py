# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict

from twitter.common.collections import maybe_list, OrderedSet
from twitter.common.python.interpreter import PythonIdentity

from pants.base.target import Target, TargetDefinitionException
from pants.targets.python_artifact import PythonArtifact
from pants.targets.with_dependencies import TargetWithDependencies
from pants.targets.with_sources import TargetWithSources


class PythonTarget(TargetWithDependencies, TargetWithSources):
  """Base class for all Python targets."""

  def __init__(self,
               name,
               sources,
               resources=None,
               dependencies=None,
               provides=None,
               compatibility=None,
               exclusives=None):
    TargetWithSources.__init__(self, name, sources=sources, exclusives=exclusives)
    TargetWithDependencies.__init__(self, name, dependencies=dependencies, exclusives=exclusives)

    self.add_labels('python')
    self.resources = self._resolve_paths(resources) if resources else OrderedSet()

    if provides and not isinstance(provides, PythonArtifact):
      raise TargetDefinitionException(self,
        "Target must provide a valid pants setup_py object. Received a '%s' object instead." %
          provides.__class__.__name__)
    self.provides = provides

    self.compatibility = maybe_list(compatibility or ())
    for req in self.compatibility:
      try:
        PythonIdentity.parse_requirement(req)
      except ValueError as e:
        raise TargetDefinitionException(self, str(e))

  def _walk(self, walked, work, predicate=None):
    super(PythonTarget, self)._walk(walked, work, predicate)
    if self.provides and self.provides.binaries:
      for binary in self.provides.binaries.values():
        binary._walk(walked, work, predicate)

  def _propagate_exclusives(self):
    self.exclusives = defaultdict(set)
    for k in self.declared_exclusives:
      self.exclusives[k] = self.declared_exclusives[k]
    for t in self.dependencies:
      if isinstance(t, Target):
        t._propagate_exclusives()
        self.add_to_exclusives(t.exclusives)
      elif hasattr(t, "declared_exclusives"):
        self.add_to_exclusives(t.declared_exclusives)
