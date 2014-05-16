# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict

from twitter.common.collections import maybe_list, OrderedSet
from twitter.common.lang import Compatibility
from twitter.common.python.interpreter import PythonIdentity

from pants.base.address import SyntheticAddress
from pants.base.payload import PythonPayload
from pants.base.target import Target
from pants.base.exceptions import TargetDefinitionException
from pants.targets.python_artifact import PythonArtifact


class PythonTarget(Target):
  """Base class for all Python targets."""

  def __init__(self,
               address=None,
               sources=None,
               resources=None,
               provides=None,
               compatibility=None,
               **kwargs):
    payload = PythonPayload(sources_rel_path=address.spec_path,
                            sources=sources or [],
                            resources=resources)
    super(PythonTarget, self).__init__(address=address, payload=payload, **kwargs)
    self.add_labels('python')

    if provides and not isinstance(provides, PythonArtifact):
      raise TargetDefinitionException(self,
        "Target must provide a valid pants setup_py object. Received a '%s' object instead." %
          provides.__class__.__name__)

    self._provides = provides

    self.compatibility = maybe_list(compatibility or ())
    for req in self.compatibility:
      try:
        PythonIdentity.parse_requirement(req)
      except ValueError as e:
        raise TargetDefinitionException(self, str(e))

  @property
  def traversable_specs(self):
    if self._provides:
      for spec in self._provides._binaries.values():
        address = SyntheticAddress(spec, relative_to=self.address.spec_path)
        yield address.spec

  @property
  def provides(self):
    if not self._provides:
      return None

    # TODO(pl): This is an awful hack
    for key, binary in self._provides._binaries.iteritems():
      if isinstance(binary, Compatibility.string):
        address = SyntheticAddress(binary, relative_to=self.address.spec_path)
        self._provides._binaries[key] = self._build_graph.get_target(address)
    return self._provides

  @property
  def resources(self):
    return self.payload.resources

  def walk(self, work, predicate=None):
    super(PythonTarget, self).walk(work, predicate)
    if self.provides and self.provides.binaries:
      for binary in self.provides.binaries.values():
        binary.walk(work, predicate)

  # TODO(pl): This can definitely be simplified, but I don't want to mess with it right now.
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
