# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.build_graph.target import Target


class CargoDist(Target):

  alias = 'cargo_dist'

  _cargo_toml = 'Cargo.toml'

  def __init__(self, address, payload=None, sources=None, **kwargs):
    if not self._cargo_toml in sources:
      raise TargetDefinitionException(
        self,
        'A file named {} must be in the same directory as the BUILD file containing this target.'
        .format(self._cargo_toml))

    if not payload:
      payload = Payload()
    sources_field = self.create_sources_field(sources, address.spec_path, key_arg='sources')
    payload.add_fields({
      'sources': sources_field,
    })

    super(CargoDist, self).__init__(address=address, payload=payload, **kwargs)
