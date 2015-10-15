# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.build_graph.address import Address, BuildFileAddress
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_file_address_mapper import BuildFileAddressMapper
from pants.build_graph.target import Target
from pants_test.base_test import BaseTest


# TODO(Eric Ayers) There are methods in BuildFileAddressMapper that are missing
# explicit unit tests: addresses_in_spec_path, spec_to_address, spec_to_addresses
class BuildFileAddressMapperTest(BaseTest):

  def test_resolve(self):
    build_file = self.add_to_build_file('BUILD', 'target(name="foo")')
    address, addressable = self.address_mapper.resolve(Address.parse('//:foo'))
    self.assertIsInstance(address, BuildFileAddress)
    self.assertEqual(build_file, address.build_file)
    self.assertEqual('foo', address.target_name)
    self.assertEqual(address.target_name, addressable.addressed_name)
    self.assertEqual(addressable.addressed_type, Target)

  def test_resolve_spec(self):
    self.add_to_build_file('BUILD', dedent("""
      target(name='foozle')
      target(name='baz')
      """))

    with self.assertRaises(AddressLookupError):
      self.address_mapper.resolve_spec('//:bad_spec')

    dependencies_addressable = self.address_mapper.resolve_spec('//:foozle')
    self.assertEqual(dependencies_addressable.addressed_type, Target)

  def test_scan_addresses(self):
    root_build_file = self.add_to_build_file('BUILD', 'target(name="foo")')
    subdir_build_file = self.add_to_build_file('subdir/BUILD', 'target(name="bar")')
    subdir_suffix_build_file = self.add_to_build_file('subdir/BUILD.suffix', 'target(name="baz")')
    with open(os.path.join(self.build_root, 'BUILD.invalid.suffix'), 'w') as invalid_build_file:
      invalid_build_file.write('target(name="foobar")')
    self.assertEquals({BuildFileAddress(root_build_file, 'foo'),
                       BuildFileAddress(subdir_build_file, 'bar'),
                       BuildFileAddress(subdir_suffix_build_file, 'baz')},
                      self.address_mapper.scan_addresses())

  def test_scan_addresses_with_excludes(self):
    root_build_file = self.add_to_build_file('BUILD', 'target(name="foo")')
    self.add_to_build_file('subdir/BUILD', 'target(name="bar")')
    spec_excludes = [os.path.join(self.build_root, 'subdir')]
    self.assertEquals({BuildFileAddress(root_build_file, 'foo')},
                      self.address_mapper.scan_addresses(spec_excludes=spec_excludes))

  def test_scan_addresses_with_root(self):
    self.add_to_build_file('BUILD', 'target(name="foo")')
    subdir_build_file = self.add_to_build_file('subdir/BUILD', 'target(name="bar")')
    subdir_suffix_build_file = self.add_to_build_file('subdir/BUILD.suffix', 'target(name="baz")')
    subdir = os.path.join(self.build_root, 'subdir')
    self.assertEquals({BuildFileAddress(subdir_build_file, 'bar'),
                       BuildFileAddress(subdir_suffix_build_file, 'baz')},
                      self.address_mapper.scan_addresses(root=subdir))

  def test_scan_addresses_with_invalid_root(self):
    with self.assertRaises(BuildFileAddressMapper.InvalidRootError):
      self.address_mapper.scan_addresses(root='subdir')

  def test_raises_invalid_build_file_reference(self):
    # reference a BUILD file that doesn't exist
    with self.assertRaisesRegexp(BuildFileAddressMapper.InvalidBuildFileReference,
                                 '^BUILD file does not exist at: .*/non-existent-path'
                                 '\s+when translating spec //non-existent-path:a'):
      self.address_mapper.spec_to_address('//non-existent-path:a')

  def test_raises_address_not_in_build_file(self):
    self.add_to_build_file('BUILD', 'target(name="foo")')

    # Create an address that doesn't exist in an existing BUILD file
    address = Address.parse(':bar')
    with self.assertRaises(BuildFileAddressMapper.AddressNotInBuildFile):
      self.address_mapper.resolve(address)

  def test_raises_address_invalid_address_error(self):
    with self.assertRaises(BuildFileAddressMapper.InvalidAddressError):
      self.address_mapper.resolve_spec("../foo")

  def test_raises_empty_build_file_error(self):
    self.add_to_build_file('BUILD', 'pass')
    with self.assertRaises(BuildFileAddressMapper.EmptyBuildFileError):
      self.address_mapper.resolve_spec('//:foo')

  def test_address_lookup_error_hierarcy(self):
    self.assertIsInstance(BuildFileAddressMapper.AddressNotInBuildFile(), AddressLookupError)
    self.assertIsInstance(BuildFileAddressMapper.EmptyBuildFileError(), AddressLookupError)
    self.assertIsInstance(BuildFileAddressMapper.InvalidBuildFileReference(), AddressLookupError)
    self.assertIsInstance(BuildFileAddressMapper.InvalidAddressError(), AddressLookupError)
    self.assertIsInstance(BuildFileAddressMapper.BuildFileScanError(), AddressLookupError)
