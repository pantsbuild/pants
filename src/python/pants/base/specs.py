# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from abc import abstractmethod

from pants.util.collections import assert_single_element
from pants.util.dirutil import fast_relpath_optional
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class Spec(AbstractClass):
  """Represents address selectors as passed from the command line.

  Supports `Single` target addresses as well as `Sibling` (:) and `Descendant` (::) selector forms.

  Note: In general, 'spec' should not be a user visible term, it is usually appropriate to
  substitute 'address' for a spec resolved to an address, or 'address selector' if you are
  referring to an unresolved spec string.
  """

  @abstractmethod
  def to_spec_string(self):
    """Returns the normalized string representation of this spec."""

  @abstractmethod
  def matching_address_families(self, address_families_dict):
    """???"""

  class AddressResolutionError(Exception): pass

  def all_address_target_pairs(self, address_families):
    addr_tgt_pairs = []
    for af in address_families:
      addr_tgt_pairs.extend(af.addressables.items())
    if len(addr_tgt_pairs) == 0:
      raise self.AddressResolutionError('Spec {} does not match any targets.'.format(self))
    return addr_tgt_pairs

  class AddressFamilyResolutionError(Exception): pass

  def address_families_for_dir(self, address_families_dict, spec_dir_path):
    maybe_af = address_families_dict.get(spec_dir_path, None)
    if maybe_af is None:
      raise self.AddressFamilyResolutionError(
        'Path "{}" does not contain any BUILD files.'
        .format(spec_dir_path))
    return [maybe_af]


class SingleAddress(datatype(['directory', 'name']), Spec):
  """A Spec for a single address."""

  def __new__(cls, directory, name):
    if directory is None or name is None:
      raise ValueError('A SingleAddress must have both a directory and name. Got: '
                       '{}:{}'.format(directory, name))
    return super(SingleAddress, cls).__new__(cls, directory, name)

  def to_spec_string(self):
    return '{}:{}'.format(self.directory, self.name)

  def matching_address_families(self, address_families_dict):
    return self.address_families_for_dir(address_families_dict, self.directory)

  class SingleAddressResolutionError(Exception):
    def __init__(self, single_address_family, name):
      super(SingleAddress.SingleAddressResolutionError, self).__init__()
      self.single_address_family = single_address_family
      self.name = name

  def all_address_target_pairs(self, address_families):
    single_af = assert_single_element(address_families)
    addr_tgt_pairs = [
      (addr, tgt) for addr, tgt in single_af.addressables.items()
      if addr.target_name == self.name
    ]
    if len(addr_tgt_pairs) == 0:
      raise self.SingleAddressResolutionError(single_af, self.name)
    # There will be at most one target with a given name in a single AddressFamily.
    assert(len(addr_tgt_pairs) == 1)
    return addr_tgt_pairs


class SiblingAddresses(datatype(['directory']), Spec):
  """A Spec representing all addresses located directly within the given directory."""

  def to_spec_string(self):
    return '{}:'.format(self.directory)

  def matching_address_families(self, address_families_dict):
    return self.address_families_for_dir(address_families_dict, self.directory)


class DescendantAddresses(datatype(['directory']), Spec):
  """A Spec representing all addresses located recursively under the given directory."""

  def to_spec_string(self):
    return '{}::'.format(self.directory)

  def matching_address_families(self, address_families_dict):
    return [
      af for ns, af in address_families_dict.items()
      if fast_relpath_optional(ns, self.directory) is not None
    ]


class AscendantAddresses(datatype(['directory']), Spec):
  """A Spec representing all addresses located recursively _above_ the given directory."""

  def to_spec_string(self):
    return '{}^'.format(self.directory)

  def matching_address_families(self, address_families_dict):
    return [
      af for ns, af in address_families_dict.items()
      if fast_relpath_optional(self.directory, ns) is not None
    ]


class Specs(datatype([('dependencies', tuple), ('tags', tuple), ('exclude_patterns', tuple)])):
  """A collection of Specs representing Spec subclasses, tags and regex filters."""

  def __new__(cls, dependencies, tags=None, exclude_patterns=tuple()):
    return super(Specs, cls).__new__(
      cls,
      dependencies=tuple(dependencies),
      tags=tuple(tags or []),
      exclude_patterns=tuple(exclude_patterns))
