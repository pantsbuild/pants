# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
from abc import abstractmethod
from builtins import str

from pants.util.collections import assert_single_element
from pants.util.dirutil import fast_relpath_optional, recursive_dirname
from pants.util.filtering import create_filters, wrap_filters
from pants.util.memo import memoized_property
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

  class AddressFamilyResolutionError(Exception): pass

  @abstractmethod
  def matching_address_families(self, address_families_dict):
    """Given a dict of (namespace path) -> AddressFamily, return the values matching this spec.

    :raises: :class:`Spec.AddressFamilyResolutionError` if no address families matched this spec.
    :return: list of AddressFamily.
    """

  @classmethod
  def address_families_for_dir(cls, address_families_dict, spec_dir_path):
    """Implementation of `matching_address_families()` for specs matching at most one directory."""
    maybe_af = address_families_dict.get(spec_dir_path, None)
    if maybe_af is None:
      raise cls.AddressFamilyResolutionError(
        'Path "{}" does not contain any BUILD files.'
        .format(spec_dir_path))
    return [maybe_af]

  class AddressResolutionError(Exception): pass

  @abstractmethod
  def address_target_pairs_from_address_families(self, address_families):
    """Given a list of AddressFamily, return (address, target) pairs matching this spec.

    :raises: :class:`SingleAddress._SingleAddressResolutionError` for resolution errors with a
             :class:`SingleAddress` instance.
    :raises: :class:`Spec.AddressResolutionError` if no targets could be found otherwise, if the
             spec type requires a non-empty set of targets.
    :return: list of (Address, Target) pairs.
    """

  @classmethod
  def all_address_target_pairs(cls, address_families):
    """Implementation of `address_target_pairs_from_address_families()` which does no filtering."""
    addr_tgt_pairs = []
    for af in address_families:
      addr_tgt_pairs.extend(af.addressables.items())
    return addr_tgt_pairs

  @abstractmethod
  def make_glob_patterns(self, address_mapper):
    """Generate glob patterns matching exactly all the BUILD files this spec covers."""

  @classmethod
  def globs_in_single_dir(cls, spec_dir_path, address_mapper):
    """Implementation of `make_glob_patterns()` which only allows a single base directory."""
    return [os.path.join(spec_dir_path, pat) for pat in address_mapper.build_patterns]


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

  class _SingleAddressResolutionError(Exception):
    def __init__(self, single_address_family, name):
      super(SingleAddress._SingleAddressResolutionError, self).__init__()
      self.single_address_family = single_address_family
      self.name = name

  def address_target_pairs_from_address_families(self, address_families):
    """Return the pair for the single target matching the single AddressFamily, or error.

    :raises: :class:`SingleAddress._SingleAddressResolutionError` if no targets could be found for a
             :class:`SingleAddress` instance.
    :return: list of (Address, Target) pairs with exactly one element.
    """
    single_af = assert_single_element(address_families)
    addr_tgt_pairs = [
      (addr, tgt) for addr, tgt in single_af.addressables.items()
      if addr.target_name == self.name
    ]
    if len(addr_tgt_pairs) == 0:
      raise self._SingleAddressResolutionError(single_af, self.name)
    # There will be at most one target with a given name in a single AddressFamily.
    assert(len(addr_tgt_pairs) == 1)
    return addr_tgt_pairs

  def make_glob_patterns(self, address_mapper):
    return self.globs_in_single_dir(self.directory, address_mapper)


class SiblingAddresses(datatype(['directory']), Spec):
  """A Spec representing all addresses located directly within the given directory."""

  def to_spec_string(self):
    return '{}:'.format(self.directory)

  def matching_address_families(self, address_families_dict):
    return self.address_families_for_dir(address_families_dict, self.directory)

  def address_target_pairs_from_address_families(self, address_families):
    return self.all_address_target_pairs(address_families)

  def make_glob_patterns(self, address_mapper):
    return self.globs_in_single_dir(self.directory, address_mapper)


class DescendantAddresses(datatype(['directory']), Spec):
  """A Spec representing all addresses located recursively under the given directory."""

  def to_spec_string(self):
    return '{}::'.format(self.directory)

  def matching_address_families(self, address_families_dict):
    return [
      af for ns, af in address_families_dict.items()
      if fast_relpath_optional(ns, self.directory) is not None
    ]

  def address_target_pairs_from_address_families(self, address_families):
    addr_tgt_pairs = self.all_address_target_pairs(address_families)
    if len(addr_tgt_pairs) == 0:
      raise self.AddressResolutionError('Spec {} does not match any targets.'.format(self))
    return addr_tgt_pairs

  def make_glob_patterns(self, address_mapper):
    return [os.path.join(self.directory, '**', pat) for pat in address_mapper.build_patterns]


class AscendantAddresses(datatype(['directory']), Spec):
  """A Spec representing all addresses located recursively _above_ the given directory."""

  def to_spec_string(self):
    return '{}^'.format(self.directory)

  def matching_address_families(self, address_families_dict):
    return [
      af for ns, af in address_families_dict.items()
      if fast_relpath_optional(self.directory, ns) is not None
    ]

  def address_target_pairs_from_address_families(self, address_families):
    return self.all_address_target_pairs(address_families)

  def make_glob_patterns(self, address_mapper):
    return [
      os.path.join(f, pattern)
      for pattern in address_mapper.build_patterns
      for f in recursive_dirname(self.directory)
    ]


class SpecsMatcher(datatype([('tags', tuple), ('exclude_patterns', tuple)])):
  """Contains filters for the output of a Specs match.

  This class is separated out from `Specs` to allow for both stuctural equality of the `tags` and
  `exclude_patterns`, and for caching of their compiled forms using `@memoized_property` (which uses
  the hash of the class instance in its key, and results in a very large key when used with `Specs`
  directly).
  """

  def __new__(cls, tags=None, exclude_patterns=tuple()):
    return super(SpecsMatcher, cls).__new__(
      cls,
      tags=tuple(tags or []),
      exclude_patterns=tuple(exclude_patterns))

  @memoized_property
  def _exclude_compiled_regexps(self):
    return [re.compile(pattern) for pattern in set(self.exclude_patterns or [])]

  def _excluded_by_pattern(self, address):
    return any(p.search(address.spec) is not None for p in self._exclude_compiled_regexps)

  @memoized_property
  def _target_tag_matches(self):
    def filter_for_tag(tag):
      return lambda t: tag in [str(t_tag) for t_tag in t.kwargs().get("tags", [])]
    return wrap_filters(create_filters(self.tags, filter_for_tag))

  def matches_target_address_pair(self, address, target):
    """
    :param Address address: An Address to match
    :param HydratedTarget target: The Target for the address.

    :return: True if the given Address/HydratedTarget are included by this matcher.
    """
    return self._target_tag_matches(target) and not self._excluded_by_pattern(address)


class Specs(datatype([('dependencies', tuple), ('matcher', SpecsMatcher)])):
  """A collection of Specs representing Spec subclasses, and a SpecsMatcher to filter results."""

  def __new__(cls, dependencies, tags=None, exclude_patterns=tuple()):
    return super(Specs, cls).__new__(
      cls,
      dependencies=tuple(dependencies),
      matcher=SpecsMatcher(tags=tags, exclude_patterns=exclude_patterns),
    )
