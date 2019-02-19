# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class CargoBaseTarget(Target):
  """A base class for all cargo targets."""

  def __init__(self, address=None, payload=None, cargo_invocation=None, **kwargs):
    payload = payload or Payload()
    payload.add_field('cargo_invocation', PrimitiveField(cargo_invocation))

    super(CargoBaseTarget, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def cargo_invocation(self):
    return self.payload.get_field_value('cargo_invocation')
