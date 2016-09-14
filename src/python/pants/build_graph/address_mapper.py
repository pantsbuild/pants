# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from abc import abstractmethod

from pants.base.specs import SingleAddress
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
  def scan_build_files(self, base_path):
    """Recursively gather all BUILD files under base_path.

    :param base_path: The path to start scanning, relative to build_root.
    :return: OrderedSet of BUILD file paths relative to build_root.
    """

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

  def check_valid_spec(self, spec_str):
    """Check if a spec str is valid.

    :param spec_str: A string representing an address.
    :return: True if given spec_str is valid, False otherwise.
    """
    try:
      address = Address.parse(spec_str)
      self.scan_specs([SingleAddress(address.spec_path, address._target_name)])
      return True
    except ValueError:
      return False
    except AddressLookupError:
      return False

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
