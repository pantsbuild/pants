# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.interpreter import PythonIdentity
from twitter.common.collections import maybe_list

from pants.backend.python.python_artifact import PythonArtifact
from pants.base.deprecated import deprecated_conditional
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.address import Address
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.build_graph.target_addressable import TargetAddressable
from pants.util.memo import memoized_property


class PythonTarget(Target):
  """Base class for all Python targets.

  :API: public
  """

  @classmethod
  def _suffix_for_synthetic_spec(cls, spec):
    """Given a spec, append the synthetic resources suffix to it for a consistent mapping."""
    return '{}_synthetic_resources'.format(spec)

  @classmethod
  def create(cls, parse_context, **kwargs):
    resources = kwargs.get('resources', None) or []
    if resources:
      deprecated_conditional(
        lambda: True,
        '1.5.0.dev0',
        'The `resources=` Python target argument', 'Depend on resources targets instead.'
      )
      resources_kwargs = dict(
        name=cls._suffix_for_synthetic_spec(kwargs.get('name', 'unknown')),
        sources=resources,
        type_alias=Resources.alias()
      )
      resource_target = parse_context.create_object(Resources.alias(), **resources_kwargs)
      if isinstance(resource_target, TargetAddressable):
        name = resource_target.addressed_name
      else:
        name = resource_target.name
      resource_target_spec = '//{}:{}'.format(parse_context.rel_path, name)
      kwargs['dependencies'] = kwargs.get('dependencies', []) + [resource_target_spec]

    parse_context.create_object(cls, type_alias=cls.alias(), **kwargs)

  def __init__(self,
               address=None,
               payload=None,
               sources=None,
               resources=None,  # Old-style resources (file list, Fileset).
               resource_targets=None,  # New-style resources (Resources target specs).
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
    :param resources: non-Python resources, e.g. templates, keys, other data
      (it is
      recommended that your application uses the pkgutil package to access these
      resources in a .zip-module friendly way.) Paths are relative to the BUILD
      file's directory.
    :type sources: ``Fileset`` or list of strings
    :param resource_targets: The addresses of ``resources`` targets this target
      depends on.
    :type resource_targets: list of strings
    :param provides:
      The `setup_py <#setup_py>`_ to publish that represents this
      target outside the repo.
    :param compatibility: either a string or list of strings that represents
      interpreter compatibility for this target, using the Requirement-style
      format, e.g. ``'CPython>=3', or just ['>=2.7','<3']`` for requirements
      agnostic to interpreter class.
    """
    deprecated_conditional(lambda: resources is not None, '1.5.0.dev0',
                           'The `resources=` Python target argument', 'Depend on resources targets instead.')
    deprecated_conditional(lambda: resource_targets is not None, '1.5.0.dev0',
                           'The `resource_targets=` Python target argument', 'Use `dependencies=` instead.')
    self.address = address
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources, address.spec_path, key_arg='sources'),
      'resources': self.create_sources_field(resources, address.spec_path, key_arg='resources'),
      'resource_targets': PrimitiveField(resource_targets),
      'provides': provides,
      'compatibility': PrimitiveField(maybe_list(compatibility or ())),
    })
    super(PythonTarget, self).__init__(address=address, payload=payload, **kwargs)
    self._resource_target_specs = resource_targets
    self.add_labels('python')

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

  @classmethod
  def compute_dependency_specs(cls, kwargs=None, payload=None):
    for spec in super(PythonTarget, cls).compute_dependency_specs(kwargs, payload):
      yield spec

    target_representation = kwargs or payload.as_dict()
    specs = target_representation.get('resource_targets', None) or []
    for spec in specs:
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
    # Note: Will correctly find:
    #   - Regular dependencies on Resources targets.
    #   - Resources targets specified via resource_targets=.
    #   - The synthetic Resources target created from the resources= fileset.
    # Because these are all in the dependency specs.
    return [dep for dep in self.dependencies if isinstance(dep, Resources)]

  def walk(self, work, predicate=None):
    super(PythonTarget, self).walk(work, predicate)
    for binary in self.provided_binaries.values():
      binary.walk(work, predicate)
