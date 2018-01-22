# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.base.build_environment import get_buildroot
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.remote_sources import RemoteSources
from pants.source.wrapped_globs import Files
from pants.task.task import Task


logger = logging.getLogger(__name__)


class DeferredSourcesMapper(Task):
  """Map DeferredSourcesFields to files that produce the product 'unpacked_archives'.

  If you want a task to be able to map sources like this, make it require the 'deferred_sources'
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

  def process_remote_sources(self):
    """Create synthetic targets with populated sources from remote_sources targets."""
    unpacked_sources = self.context.products.get_data('unpacked_archives')
    remote_sources_targets = self.context.targets(predicate=lambda t: isinstance(t, RemoteSources))
    for target in remote_sources_targets:
      sources, rel_unpack_dir = unpacked_sources[target.sources_target]
      synthetic_target = self.context.add_new_target(
        address=Address(os.path.relpath(self.workdir, get_buildroot()), target.id),
        target_type=target.destination_target_type,
        dependencies=target.dependencies,
        sources=Files.create_fileset_with_spec(rel_unpack_dir, *sources),
        derived_from=target,
        **target.destination_target_args
      )
      for dependent in self.context.build_graph.dependents_of(target.address):
        self.context.build_graph.inject_dependency(dependent, synthetic_target.address)

  def execute(self):
    self.process_remote_sources()
