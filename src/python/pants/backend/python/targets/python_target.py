# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pex.interpreter import PythonIdentity
from twitter.common.collections import maybe_list

from pants.backend.core.targets.resources import Resources
from pants.backend.python.python_artifact import PythonArtifact
from pants.base.address import SyntheticAddress
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField, SourcesField
from pants.base.target import Target


class PythonTarget(Target):
  """Base class for all Python targets."""

  def __init__(self,
               address=None,
               payload=None,
               sources_rel_path=None,
               sources=None,
               resources=None,  # Old-style resources (file list, Fileset).
               resource_targets=None,  # New-style resources (Resources target specs).
               provides=None,
               compatibility=None,
               **kwargs):
    """
    :param dependencies: Other targets that this target depends on.
      These dependencies may
      be ``python_library``-like targets (``python_library``,
      ``python_thrift_library``, ``python_antlr_library`` and so forth) or
      ``python_requirement_library`` targets.
    :type dependencies: List of target specs
    :param sources: Files to "include". Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param resources: non-Python resources, e.g. templates, keys, other data
      (it is
      recommended that your application uses the pkgutil package to access these
      resources in a .zip-module friendly way.)
    :param provides:
      The `setup_py <#setup_py>`_ to publish that represents this
      target outside the repo.
    :param compatibility: either a string or list of strings that represents
      interpreter compatibility for this target, using the Requirement-style
      format, e.g. ``'CPython>=3', or just ['>=2.7','<3']`` for requirements
      agnostic to interpreter class.
    """
    self.address=address
    if sources_rel_path is None:
      sources_rel_path = address.spec_path
    payload = payload or Payload()
    payload.add_fields({
      'sources': SourcesField(sources=self.assert_list(sources),
                              sources_rel_path=sources_rel_path),
      'resources': SourcesField(sources=self.assert_list(resources),
                                sources_rel_path=address.spec_path),
      'provides': provides,
      'compatibility': PrimitiveField(maybe_list(compatibility or ())),
    })
    super(PythonTarget, self).__init__(address=address, payload=payload, **kwargs)
    self._resource_target_specs = resource_targets
    self.add_labels('python')

    self._synthetic_resources_target = None

    if provides and not isinstance(provides, PythonArtifact):
      raise TargetDefinitionException(self,
        "Target must provide a valid pants setup_py object. Received a '%s' object instead." %
          provides.__class__.__name__)

    self._provides = provides

    # Check that the compatibility requirements are well-formed.
    for req in self.payload.compatibility:
      try:
        PythonIdentity.parse_requirement(req)
      except ValueError as e:
        raise TargetDefinitionException(self, str(e))

  @property
  def traversable_specs(self):
    for spec in super(PythonTarget, self).traversable_specs:
      yield spec
    if self._provides:
      for spec in self._provides._binaries.values():
        address = SyntheticAddress.parse(spec, relative_to=self.address.spec_path)
        yield address.spec

  @property
  def provides(self):
    return self.payload.provides

  @property
  def provided_binaries(self):
    def binary_iter():
      if self.payload.provides:
        for key, binary_spec in self.payload.provides.binaries.items():
          address = SyntheticAddress.parse(binary_spec, relative_to=self.address.spec_path)
          yield (key, self._build_graph.get_target(address))
    return dict(binary_iter())

  @property
  def compatibility(self):
    return self.payload.compatibility

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

    if self.payload.resources.source_paths:
      if not self._synthetic_resources_target:
        # This must happen lazily: we don't have enough context in __init__() to do this there.
        self._synthetic_resources_target = self._synthesize_resources_target()
      resource_targets.append(self._synthetic_resources_target)

    return resource_targets

  def walk(self, work, predicate=None):
    super(PythonTarget, self).walk(work, predicate)
    for binary in self.provided_binaries.values():
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
                                              sources=self.payload.resources.source_paths,
                                              derived_from=self)
    return self._build_graph.get_target(synthetic_address)
