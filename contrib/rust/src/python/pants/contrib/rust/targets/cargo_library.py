# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.payload import Payload

from pants.contrib.rust.targets.cargo_base_library import CargoBaseLibrary


class CargoLibrary(CargoBaseLibrary):
  """A base class for all cargo targets."""

  def __init__(self, address=None, payload=None, sources=None, **kwargs):
    payload = payload or Payload()

    if sources:
      payload.add_field('sources', self.create_sources_field(sources=sources,
                                                             sources_rel_path=address.spec_path,
                                                             key_arg='sources'))

    super(CargoLibrary, self).__init__(address=address, payload=payload, **kwargs)
