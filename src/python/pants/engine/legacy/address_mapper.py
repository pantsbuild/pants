# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from twitter.common.collections import OrderedSet

from pants.base.specs import DescendantAddresses, SiblingAddresses
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.address_mapper import AddressMapper


logger = logging.getLogger(__name__)


class LegacyAddressMapper(AddressMapper):

  def __init__(self, graph):
    self._graph = graph

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
    addresses = set()
    for address in self._graph.inject_specs_closure([DescendantAddresses('')]):
      addresses.add(address)
    return addresses
