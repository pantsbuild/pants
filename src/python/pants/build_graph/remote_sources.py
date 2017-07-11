# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.address import Address
from pants.build_graph.target import Target


class RemoteSources(Target):
  """A target that generates a synthetic target using deferred sources.

  This provides a mechanism for using the contents of a jar as sources for another target. The jar
  where the sources are specified from is given via the `sources_target` parameter, and the type for
  the target that should be created with those sources is given via the `dest` parameter. Any
  additional arguments for the new target go into the `args` parameter.
  """

  def __init__(self, address=None, payload=None, sources_target=None, dest=None, args=None,
               **kwargs):
    """
    :API: public

    :param string sources_target: The address of the (typically unpacked_jars) target to get sources
      from.
    :param dest: The target type of the synthetic target to generate (eg, java_library).
    :param dict args: Any additional arguments necessary to construct the synthetic destination
      target (sources and dependencies are supplied automatically).
    """
    self.address = address
    if not sources_target:
      raise TargetDefinitionException(self, 'You must specify the address of a target to acquire '
                                            'sources from via the "sources_target" parameter.')
    if not dest or not hasattr(dest, 'target_types'):
      raise TargetDefinitionException(self, 'You must specify a target type for the "dest" '
                                            'parameter.')
    if len(dest.target_types) != 1:
      raise TargetDefinitionException(
        self,
        'Target alias {} has multiple possible target types {}.'.format(dest, dest.target_types),
      )
    dest = dest.target_types[0]
    self._dest = dest
    self._dest_args = args
    payload = payload or Payload()
    payload.add_fields({
      'sources_target_spec': PrimitiveField(self._sources_target_to_spec(address, sources_target)),
      'dest': PrimitiveField(dest.__name__),
    })
    super(RemoteSources, self).__init__(address=address, payload=payload, **kwargs)

  @staticmethod
  def _sources_target_to_spec(address, sources_target):
    return Address.parse(sources_target, relative_to=address.spec_path).spec

  @classmethod
  def compute_dependency_specs(cls, kwargs=None, payload=None):
    for spec in super(RemoteSources, cls).compute_dependency_specs(kwargs, payload):
      yield spec

    if kwargs:
      address = kwargs.get('address')
      sources_target = kwargs.get('sources_target')
      if address and sources_target:
        yield cls._sources_target_to_spec(address, sources_target)
    elif payload:
      payload_dict = payload.as_dict()
      yield payload_dict['sources_target_spec']

  @property
  def sources_target(self):
    return self._build_graph.get_target_from_spec(self.payload.sources_target_spec)

  @property
  def destination_target_type(self):
    return self._dest

  @property
  def destination_target_args(self):
    return self._dest_args or {}
