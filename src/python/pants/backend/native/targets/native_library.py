# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


logger = logging.getLogger(__name__)


class NativeLibrary(Target):
  """???"""

  @classmethod
  def provides_native_artifact(cls, target):
    return isinstance(target, cls) and bool(target.provides)

  def __init__(self, address, payload=None, sources=None, provides=None,
               strict_deps=None, fatal_warnings=None, **kwargs):
    logger.debug("address: {}".format(address))
    logger.debug("sources: {}".format(sources))

    if not payload:
      payload = Payload()
    sources_field = self.create_sources_field(sources, address.spec_path, key_arg='sources')
    payload.add_fields({
      'sources': sources_field,
      'provides': provides,
      'strict_deps': PrimitiveField(strict_deps),
      'fatal_warnings': PrimitiveField(fatal_warnings),
    })

    logger.debug("sources_field.sources: {}".format(sources_field.sources))

    if provides and not isinstance(provides, NativeArtifact):
      raise TargetDefinitionException(
        "Target must provide a valid pants '{}' object. Received an object with type '{}' "
        "and value: {}."
        .format(NativeArtifact.alias(), type(provides).__name__, provides))

    super(NativeLibrary, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def strict_deps(self):
    return self.payload.strict_deps

  @property
  def fatal_warnings(self):
    return self.payload.fatal_warnings

  @property
  def provides(self):
    return self.payload.provides
