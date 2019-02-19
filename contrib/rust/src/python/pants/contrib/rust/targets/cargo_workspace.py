# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.base.build_environment import get_buildroot
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

from pants.contrib.rust.targets.cargo_target import CargoTarget


class CargoWorkspace(CargoTarget):
  """A class for a cargo workspace target."""

  def __init__(self, address=None, manifest=None, toolchain=None, members=None, include=None,
               payload=None, **kwargs):
    if manifest is not None:
      manifest = os.path.join(get_buildroot(), address.spec_path, manifest)

    if toolchain is not None:
      toolchain = os.path.join(get_buildroot(), address.spec_path, toolchain)

    payload = payload or Payload()

    member_paths = list(map(lambda member: os.path.join(address.spec_path, member), members))
    payload.add_field('member_names', PrimitiveField(members))
    payload.add_field('member_paths', PrimitiveField(member_paths))

    payload.add_field('include_sources', PrimitiveField(include))

    super(CargoWorkspace, self).__init__(address=address, manifest=manifest, toolchain=toolchain,
                                         payload=payload, **kwargs)

  @property
  def member_paths(self):
    return self.payload.get_field_value('member_paths')

  @property
  def member_names(self):
    return self.payload.get_field_value('member_names')

  @property
  def include_sources(self):
    return self.payload.get_field_value('include_sources')
