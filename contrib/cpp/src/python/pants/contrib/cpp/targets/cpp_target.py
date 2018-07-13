# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.payload import Payload
from pants.build_graph.target import Target


class CppTarget(Target):
  """A base class for all cpp targets."""

  def __init__(self, address=None, payload=None, sources=None, **kwargs):
    """
    :param sources: Source code files to build. Paths are relative to the BUILD file's directory.
    :type sources: :class:`pants.source.wrapped_globs.FilesetWithSpec` (from globs or rglobs) or
                   list of strings
    """
    payload = payload or Payload()
    payload.add_field('sources', self.create_sources_field(sources=sources,
                                                           sources_rel_path=address.spec_path,
                                                           key_arg='sources'))
    super(CppTarget, self).__init__(address=address, payload=payload, **kwargs)
