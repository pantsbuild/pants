# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from abc import abstractmethod

from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.util.meta import AbstractClass


logger = logging.getLogger(__name__)


class AddressMapper(AbstractClass):
  """Maps specs into valid addresses and their associated addressables."""

  class AddressNotInBuildFile(AddressLookupError):
    """Indicates an address cannot be found in an existing BUILD file."""

  class EmptyBuildFileError(AddressLookupError):
    """Indicates no addresses are defined in a BUILD file."""

  class InvalidBuildFileReference(AddressLookupError):
    """Indicates no BUILD file exists at the address referenced."""

  class InvalidAddressError(AddressLookupError):
    """Indicates an address cannot be parsed."""

  class BuildFileScanError(AddressLookupError):
    """Indicates a problem was encountered scanning a tree of BUILD files."""

  class InvalidRootError(BuildFileScanError):
    """Indicates an invalid scan root was supplied."""

  @abstractmethod
  def addresses_in_spec_path(self, spec_path):
    """Returns the addresses of targets defined at spec_path.

    :raises BuildFileScanError if there are no addresses defined at spec_path.
    :param spec_path: The path to look for addresses at.
    :return: Addresses of targets at spec_path.
    """

  @abstractmethod
  def scan_specs(self, specs, fail_fast=True):
    """Execute a collection of `specs.Spec` objects and return an ordered set of Addresses."""

  @abstractmethod
  def resolve(self, address):
    """Maps an address in the virtual address space to an object.

    :param Address address: the address to lookup in a BUILD file
    :raises AddressLookupError: if the path to the address is not found.
    :returns: A tuple of the natively mapped BuildFileAddress and the Addressable it points to.
    """

  def resolve_spec(self, spec):
    """Converts a spec to an address and maps it to an addressable using `resolve`.

    :param spec: A string representing an address.
    :raises InvalidAddressError: if there is a problem parsing the spec.
    :raises AddressLookupError: if the address is not found.
    :return: An addressable. Usually a target.
    """
    try:
      address = Address.parse(spec)
    except ValueError as e:
      raise self.InvalidAddressError(e)
    _, addressable = self.resolve(address)
    return addressable

  @abstractmethod
  def scan_addresses(self, root=None):
    """Recursively gathers all addresses visible under `root` of the virtual address space.

    :param string root: The absolute path of the root to scan; defaults to the root directory of the
                        pants project.
    :rtype: set of :class:`pants.build_graph.address.Address`
    :raises AddressLookupError: if there is a problem parsing a BUILD file
    """

  @abstractmethod
  def is_declaring_file(self, address, file_path):
    """Returns True if the address could be declared in the file at file_path.

    :param Address address: The address to check for.
    :param string file_path: The path of the file that may contain a declaration for the address.
    """

  def _raise_incorrect_address_error(self, spec_path, wrong_target_name, addresses):
    """Search through the list of targets and return those which originate from the same folder
    which wrong_target_name resides in.

    :raises: A helpful error message listing possible correct target addresses.
    """
    was_not_found_message = '{target_name} was not found in BUILD files from {spec_path}'.format(
      target_name=wrong_target_name, spec_path=spec_path)

    if not addresses:
      raise self.EmptyBuildFileError(
        '{was_not_found_message}, because that directory contains no BUILD files defining addressable entities.'
          .format(was_not_found_message=was_not_found_message))
    # Print BUILD file extensions if there's more than one BUILD file with targets only.
    if (any(not hasattr(address, 'build_file') for address in addresses) or
        len(set([address.build_file for address in addresses])) == 1):
      specs = [':{}'.format(address.target_name) for address in addresses]
    else:
      specs = [':{} (from {})'.format(address.target_name, os.path.basename(address.build_file.relpath))
               for address in addresses]

    # Might be neat to sort by edit distance or something, but for now alphabetical is fine.
    specs = [''.join(pair) for pair in sorted(specs)]

    # Give different error messages depending on whether BUILD file was empty.
    one_of = ' one of' if len(specs) > 1 else ''  # Handle plurality, just for UX.
    raise self.AddressNotInBuildFile(
      '{was_not_found_message}. Perhaps you '
      'meant{one_of}: \n  {specs}'.format(was_not_found_message=was_not_found_message,
                                          one_of=one_of,
                                          specs='\n  '.join(specs)))
