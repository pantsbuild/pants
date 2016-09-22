# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from twitter.common.collections import OrderedSet

from pants.base.build_file import BuildFile
from pants.base.specs import DescendantAddresses, SiblingAddresses
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.address_mapper import AddressMapper
from pants.util.dirutil import fast_relpath


logger = logging.getLogger(__name__)


class LegacyAddressMapper(AddressMapper):
  """Provides a facade over the engine backed build graph.

  This allows tasks to use the context's address_mapper when the v2 engine is enabled.
  """

  def __init__(self, graph, build_root):
    self._build_root = build_root
    self._graph = graph

  @staticmethod
  def is_declaring_file(address, file_path):
    # NB: this will cause any BUILD file, whether it contains the address declaration or not to be
    # considered the one that declared it. That's ok though, because the spec path should be enough
    # information for debugging most of the time.
    #
    # We could call into the engine to ask for the file that declared the address.
    return (os.path.dirname(file_path) == address.spec_path and
            BuildFile._is_buildfile_name(os.path.basename(file_path)))

  def addresses_in_spec_path(self, spec_path):
    try:
      return set(self._graph.inject_specs_closure([SiblingAddresses(spec_path)]))
    except AddressLookupError as e:
      raise self.BuildFileScanError(str(e))

  def scan_specs(self, specs, fail_fast=True):
    try:
      return OrderedSet(self._graph.inject_specs_closure(specs, fail_fast))
    except AddressLookupError as e:
      raise self.BuildFileScanError(str(e))

  def resolve(self, address):
    try:
      target = self._graph.get_target(address)
      if not target:
        try:
          addresses = self.addresses_in_spec_path(address.spec_path)
        except AddressLookupError:
          addresses = set()

        raise self._raise_incorrect_address_error(address.spec_path, address.target_name, addresses)
      return address, target

    except AddressLookupError as e:
      raise self.BuildFileScanError(str(e))

  def scan_addresses(self, root=None):
    if root:
      try:
        base_path = fast_relpath(root, self._build_root)
      except ValueError as e:
        raise self.InvalidRootError(e)
    else:
      base_path = ''

    addresses = set()
    for address in self._graph.inject_specs_closure([DescendantAddresses(base_path)]):
      addresses.add(address)
    return addresses
