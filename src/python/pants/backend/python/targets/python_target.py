# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pex.interpreter import PythonIdentity
from twitter.common.collections import maybe_list

from pants.backend.python.python_artifact import PythonArtifact
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.address import Address
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target


class PythonTarget(Target):
  """Base class for all Python targets.

  :API: public
  """

  def __init__(self,
               address=None,
               payload=None,
               sources=None,
               provides=None,
               compatibility=None,
               **kwargs):
    """
    :param dependencies: The addresses of targets that this target depends on.
      These dependencies may
      be ``python_library``-like targets (``python_library``,
      ``python_thrift_library``, ``python_antlr_library`` and so forth) or
      ``python_requirement_library`` targets.
    :type dependencies: list of strings
    :param sources: Files to "include". Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param provides:
      The `setup_py <#setup_py>`_ to publish that represents this
      target outside the repo.
    :param compatibility: either a string that represents interpreter compatibility for this target
      using the Requirement-style format, e.g. ``'CPython>=2.7,<3'`` (Select a CPython interpreter
      with version ``>=2.7`` AND version ``<3``) or a list of Requirement-style strings which will
      be OR'ed together. If the compatibility requirement is agnostic to interpreter class, using
      the example above, a Requirement-style compatibility constraint like '>=2.7,<3' (N.B.: not
      prefixed with CPython) can be used.
    """
    self.address = address
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources, address.spec_path, key_arg='sources'),
      'provides': provides,
      'compatibility': PrimitiveField(maybe_list(compatibility or ())),
    })
    super(PythonTarget, self).__init__(address=address, payload=payload, **kwargs)

    if provides and not isinstance(provides, PythonArtifact):
      raise TargetDefinitionException(self,
        "Target must provide a valid pants setup_py object. Received a '{}' object instead.".format(
          provides.__class__.__name__))

    self._provides = provides

    # Check that the compatibility requirements are well-formed.
    for req in self.payload.compatibility:
      try:
        PythonIdentity.parse_requirement(req)
      except ValueError as e:
        raise TargetDefinitionException(self, str(e))

  @classmethod
  def compute_injectable_specs(cls, kwargs=None, payload=None):
    for spec in super(PythonTarget, cls).compute_injectable_specs(kwargs, payload):
      yield spec

    target_representation = kwargs or payload.as_dict()
    provides = target_representation.get('provides', None) or []
    if provides:
      for spec in provides._binaries.values():
        yield spec

  @property
  def provides(self):
    return self.payload.provides

  @property
  def provided_binaries(self):
    def binary_iter():
      if self.payload.provides:
        for key, binary_spec in self.payload.provides.binaries.items():
          address = Address.parse(binary_spec, relative_to=self.address.spec_path)
          yield (key, self._build_graph.get_target(address))
    return dict(binary_iter())

  @property
  def compatibility(self):
    return self.payload.compatibility

  @property
  def resources(self):
    return [dep for dep in self.dependencies if isinstance(dep, Resources)]

  def walk(self, work, predicate=None):
    super(PythonTarget, self).walk(work, predicate)
    for binary in self.provided_binaries.values():
      binary.walk(work, predicate)
