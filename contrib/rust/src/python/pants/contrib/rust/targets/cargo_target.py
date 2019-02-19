# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.base.build_environment import get_buildroot
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class CargoTarget(Target):
  """A base class for all cargo targets."""

  def __init__(self, address=None, sources=None, manifest=None, toolchain=None, payload=None,
               **kwargs):
    """
    :param sources: Source code files to build. Paths are relative to the BUILD file's directory.
    :type sources: :class:`pants.source.wrapped_globs.FilesetWithSpec` (from globs or rglobs) or
                   list of strings
    :param manifest: The path of the Cargo.toml file (relative to the BUILD file directory). Default is the path of the BUILD file directory.
    :type manifest: String
    :param toolchain: The path of the rust-toolchain file (relative to the BUILD file directory). Default is the path of the BUILD file directory.
    :type toolchain: String
    """

    payload = payload or Payload()

    payload.add_field('sources', self.create_sources_field(sources=sources,
                                                           sources_rel_path=address.spec_path,
                                                           key_arg='sources'))

    manifest_default = os.path.join(get_buildroot(), address.spec_path)
    toolchain_default = os.path.join(get_buildroot(), address.spec_path)

    payload.add_field('manifest', PrimitiveField(manifest or manifest_default))
    payload.add_field('toolchain', PrimitiveField(toolchain or toolchain_default))

    super(CargoTarget, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def manifest(self):
    return self.payload.get_field_value('manifest')

  @property
  def toolchain(self):
    return self.payload.get_field_value('toolchain')
