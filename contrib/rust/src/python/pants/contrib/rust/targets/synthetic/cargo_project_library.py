# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.payload import Payload

from pants.contrib.rust.targets.synthetic.cargo_synthetic_library import CargoSyntheticLibrary


class CargoProjectLibrary(CargoSyntheticLibrary):
  """A base class for all synthetic project related cargo library targets."""

  def __init__(self, address=None, payload=None, sources=None, **kwargs):
    payload = payload or Payload()

    if sources:
      payload.add_field('sources', self.create_sources_field(sources=sources,
                                                             sources_rel_path=address.spec_path,
                                                             key_arg='sources'))

    super(CargoProjectLibrary, self).__init__(address=address, payload=payload, **kwargs)
