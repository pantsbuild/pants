# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.payload import Payload
from pants.build_graph.target import Target


class CargoDist(Target):

  def __init__(self, address, payload=None, sources=None, **kwargs):
    if not payload:
      payload = Payload()
    sources_field = self.create_sources_field(sources, address.spec_path, key_arg='sources')
    payload.add_fields({
      'sources': sources_field,
    })

    super(CargoDist, self).__init__(address=address, payload=payload, **kwargs)
