# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.backend.core.tasks.task import Task
from pants.base.address_lookup_error import AddressLookupError
from pants.base.payload_field import DeferredSourcesField
from pants.base.source_root import SourceRoot


logger = logging.getLogger(__name__)


class DeferredSourcesMapper(Task):
  """Map DeferredSorucesFields to files that produce product 'unpacked_archives', like UnpackJars

  If you want a task to be able to map sources like this, make it require the  'deferred_sources'
  product.
  """

  class SourcesTargetLookupError(AddressLookupError):
    """Raised when the referenced target cannot be found in the build graph"""
    pass

  class NoUnpackedSourcesError(AddressLookupError):
    """Raised when there are no files found unpacked from the archive"""
    pass

  @classmethod
  def product_types(cls):
    """
    Declare product produced by this task

    deferred_sources does not have any data associated with it. Downstream tasks can
    depend on it just make sure that this task completes first.
    :return:
    """
    return ['deferred_sources']

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('unpacked_archives')

  def execute(self):
    deferred_sources_fields = []
    def find_deferred_sources_fields(target):
      for name, payload_field in target.payload.fields:
        if isinstance(payload_field, DeferredSourcesField):
          deferred_sources_fields.append((target, name, payload_field))
    addresses = [target.address for target in self.context.targets()]
    self.context.build_graph.walk_transitive_dependency_graph(addresses,
                                                              find_deferred_sources_fields)

    unpacked_sources = self.context.products.get_data('unpacked_archives')
    for (target, name, payload_field) in deferred_sources_fields:
      sources_target = self.context.build_graph.get_target(payload_field.address)
      if not sources_target:
        raise self.SourcesTargetLookupError(
          "Couldn't find {sources_spec} referenced from {target} field {name} in build graph"
          .format(sources_spec=payload_field.address.spec, target=target.address.spec, name=name))
      if not sources_target in unpacked_sources:
        raise self.NoUnpackedSourcesError(
          "Target {sources_spec} referenced from {target} field {name} did not unpack any sources"
          .format(spec=sources_target.address.spec, target=target.address.spec, name=name))
      sources, rel_unpack_dir = unpacked_sources[sources_target]
      SourceRoot.register_mutable(rel_unpack_dir)
      payload_field.populate(sources, rel_unpack_dir)
