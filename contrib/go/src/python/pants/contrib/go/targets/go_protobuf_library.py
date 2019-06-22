# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.payload import Payload
from pants.base.payload_field import PrimitivesSetField
from pants.build_graph.target import Target

from pants.contrib.go.targets.go_local_source import GoLocalSource
from pants.contrib.go.targets.go_target import GoTarget


class GoProtobufLibrary(Target):
  """A Go library generated from Protobuf IDL files."""

  default_sources_globs = '*.proto'

  def __init__(self,
               address=None,
               payload=None,
               sources=None,
               protoc_plugins=None,
               **kwargs):
    """
    :param sources: protobuf source files
    :type sources: :class:`pants.source.wrapped_globs.FilesetWithSpec` or list of strings. Paths
                   are relative to the BUILD file's directory.
    """
    payload = payload or Payload()
    payload.add_field('sources',
                      self.create_sources_field(sources, address.spec_path, key_arg='sources'))
    payload.add_field('protoc_plugins',
                      PrimitivesSetField(protoc_plugins or []))

    super().__init__(payload=payload, address=address, **kwargs)

  @classmethod
  def alias(cls):
    return 'go_protobuf_library'

  @property
  def protoc_plugins(self):
    """The names of protoc plugins to use when generating code from this target.

    :rtype: list of strings.
    """
    return self.payload.protoc_plugins


class GoProtobufGenLibrary(GoTarget):
  """A target encapsulating the generated .go sources."""

  def __init__(self, sources=None, address=None, payload=None, **kwargs):
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources=sources,
                                           sources_rel_path=address.spec_path,
                                           key_arg='sources'),
    })
    super().__init__(address=address, payload=payload, **kwargs)

  @property
  def import_path(self):
    """The import path as used in import statements in `.go` source files."""
    return GoLocalSource.local_import_path(self.target_base, self.address)
