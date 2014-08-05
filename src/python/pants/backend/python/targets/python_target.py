# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


from pex.interpreter import PythonIdentity
from twitter.common.collections import maybe_list
from twitter.common.lang import Compatibility

from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.core.targets.resources import Resources
from pants.base.address import SyntheticAddress
from pants.base.payload import PythonPayload
from pants.base.target import Target
from pants.base.exceptions import TargetDefinitionException


class PythonTarget(Target):
  """Base class for all Python targets."""

  def __init__(self,
               address=None,
               sources=None,
               resources=None,  # Old-style resources (file list, Fileset).
               resource_targets=None,  # New-style resources (Resources target specs).
               provides=None,
               compatibility=None,
               **kwargs):
    payload = PythonPayload(sources_rel_path=address.spec_path,
                            sources=sources or [],
                            resources=resources)
    super(PythonTarget, self).__init__(address=address, payload=payload, **kwargs)
    self._resource_target_specs = resource_targets
    self.add_labels('python')

    self._synthetic_resources_target = None

    if provides and not isinstance(provides, PythonArtifact):
      raise TargetDefinitionException(self,
        "Target must provide a valid pants setup_py object. Received a '%s' object instead." %
          provides.__class__.__name__)

    self._provides = provides

    self._compatibility = maybe_list(compatibility or ())
    # Check that the compatibility requirements are well-formed.
    for req in self._compatibility:
      try:
        PythonIdentity.parse_requirement(req)
      except ValueError as e:
        raise TargetDefinitionException(self, str(e))

  @property
  def traversable_specs(self):
    if self._provides:
      for spec in self._provides._binaries.values():
        address = SyntheticAddress.parse(spec, relative_to=self.address.spec_path)
        yield address.spec

  @property
  def provides(self):
    if not self._provides:
      return None

    # TODO(pl): This is an awful hack
    for key, binary in self._provides._binaries.iteritems():
      if isinstance(binary, Compatibility.string):
        address = SyntheticAddress.parse(binary, relative_to=self.address.spec_path)
        self._provides._binaries[key] = self._build_graph.get_target(address)
    return self._provides

  @property
  def compatibility(self):
    return self._compatibility

  @property
  def resources(self):
    resource_targets = []

    if self._resource_target_specs:
      def get_target(spec):
        tgt = self._build_graph.get_target_from_spec(spec)
        if tgt is None:
          raise TargetDefinitionException(self, 'No such resource target: %s' % spec)
        return tgt
      resource_targets.extend(map(get_target, self._resource_target_specs))

    if self.payload.resources:
      if not self._synthetic_resources_target:
        # This must happen lazily: we don't have enough context in __init__() to do this there.
        self._synthetic_resources_target = self._synthesize_resources_target()
      resource_targets.append(self._synthetic_resources_target)

    return resource_targets

  def walk(self, work, predicate=None):
    super(PythonTarget, self).walk(work, predicate)
    if self.provides and self.provides.binaries:
      for binary in self.provides.binaries.values():
        binary.walk(work, predicate)

  def _synthesize_resources_target(self):
    # Create an address for the synthetic target.
    spec = self.address.spec + '_synthetic_resources'
    synthetic_address = SyntheticAddress.parse(spec=spec)
    # For safety, ensure an address that's not used already, even though that's highly unlikely.
    while self._build_graph.contains_address(synthetic_address):
      spec += '_'
      synthetic_address = SyntheticAddress.parse(spec=spec)

    self._build_graph.inject_synthetic_target(synthetic_address, Resources,
                                              sources=self.payload.resources,
                                              derived_from=self)
    return self._build_graph.get_target(synthetic_address)
