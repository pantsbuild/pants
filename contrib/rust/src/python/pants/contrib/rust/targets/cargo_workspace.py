# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

import toml
from pants.base.build_environment import get_buildroot
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

from pants.contrib.rust.targets.cargo_target import CargoTarget


class CargoWorkspace(CargoTarget):
  """A class for a cargo workspace target."""

  def __init__(self, address=None, manifest=None, toolchain=None, include=None,
               payload=None, **kwargs):
    if manifest is not None:
      manifest = os.path.join(get_buildroot(), address.spec_path, manifest)
    else:
      manifest = os.path.join(get_buildroot(), address.spec_path)

    if toolchain is not None:
      toolchain = os.path.join(get_buildroot(), address.spec_path, toolchain)
    else:
      toolchain = os.path.join(get_buildroot(), address.spec_path)

    payload = payload or Payload()

    member_toml_paths = self.get_member_paths(manifest)
    member_names = self.get_member_names(manifest, member_toml_paths)
    member_src_paths = list(
      map(lambda path: os.path.join(address.spec_path, path), member_toml_paths))

    payload.add_field('member_names', PrimitiveField(member_names))
    payload.add_field('member_paths', PrimitiveField(member_src_paths))

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

  def get_member_paths(self, workspace_manifest):
    workspace_toml_path = os.path.join(workspace_manifest, 'Cargo.toml')
    workspace_toml = toml.load(workspace_toml_path)
    member_paths = workspace_toml['workspace']['members']

    return member_paths

  def get_member_names(self, workspace_manifest, member_paths):
    member_names = []
    for member_path in member_paths:
      member_toml_path = os.path.join(workspace_manifest, member_path, 'Cargo.toml')
      member_toml = toml.load(member_toml_path)
      member_names.append(member_toml['package']['name'])
    return member_names
