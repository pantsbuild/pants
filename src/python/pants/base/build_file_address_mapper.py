# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from threading import Event

from pants.base.address import BuildFileAddress, parse_spec, SyntheticAddress
from pants.base.build_file import BuildFile
from pants.base.build_environment import get_buildroot


class AddressLookupError(Exception): pass


class BuildFileAddressMapper(object):
  """Maps addresses in the pants virtual address space to corresponding BUILD file declarations.
  """

  def __init__(self, build_file_parser):
    self._build_file_parser = build_file_parser
    self._spec_path_to_address_map_map = {}  # {spec_path: {address: addressable}} mapping

  @property
  def root_dir(self):
    return self._build_file_parser._root_dir

  def resolve(self, address):
    """Maps an address in the virtual address space to an object."""
    address_map = self.address_map_from_spec_path(address.spec_path)
    if address not in address_map:
      raise AddressLookupError("Failed to resolve address {address}".format(address=address))
    else:
      return address_map[address]

  def resolve_spec(self, spec):
    """Converts a spec to an address and maps it using `resolve`"""
    address = SyntheticAddress.parse(spec)
    return self.resolve(address)

  def address_map_from_spec_path(self, spec_path):
    """Returns a resolution map of all addresses in a "directory" in the virtual address space.

    :returns {Address: <resolved Object>}:
    """
    if spec_path not in self._spec_path_to_address_map_map:
      address_map = self._build_file_parser.address_map_from_spec_path(spec_path)
      self._spec_path_to_address_map_map[spec_path] = address_map
    return self._spec_path_to_address_map_map[spec_path]

  def addresses_in_spec_path(self, spec_path):
    """Returns only the addresses gathered by `address_map_from_spec_path`, with no values."""
    return self.address_map_from_spec_path(spec_path).keys()

  def spec_to_address(self, spec, relative_to=''):
    """A helper method for mapping a spec to the correct BuildFileAddress."""
    spec_path, name = parse_spec(spec, relative_to=relative_to)
    build_file = BuildFile.from_cache(self.root_dir, spec_path)
    return BuildFileAddress(build_file, name)

  def specs_to_addresses(self, specs, relative_to=''):
    """The equivalent of `spec_to_address` for a group of specs all relative to the same path."""
    for spec in specs:
      yield self.spec_to_address(spec, relative_to=relative_to)

  def scan_addresses(self, root=None):
    """Recursively gathers all addresses visible under `root` of the virtual address space.

    :param path root: defaults to the root directory of the pants project.
    """
    addresses = set()
    for build_file in BuildFile.scan_buildfiles(root or get_buildroot()):
      for address in self.addresses_in_spec_path(build_file.spec_path):
        addresses.add(address)
    return addresses

