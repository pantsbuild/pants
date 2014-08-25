# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

from pants.backend.core.targets.dependencies import Dependencies
from pants.base.address import BuildFileAddress
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_file_address_mapper import BuildFileAddressMapper

from pants_test.base_test import BaseTest


class BuildFileAddressMapperTest(BaseTest):
  def setUp(self):
    super(BuildFileAddressMapperTest, self).setUp()

  def test_resolve(self):
    build_file = self.add_to_build_file('BUILD', dedent(
      ''' dependencies(
        name = 'foo'
      )
      '''
    ))

    address = BuildFileAddress(build_file, 'foo')
    addressable = self.address_mapper.resolve(address)
    self.assertEquals(address.target_name, addressable.addressable_name)
    self.assertEqual(addressable.target_type, Dependencies)

  def test_resolve_spec(self):
    self.add_to_build_file('BUILD', dedent(
      '''
      dependencies(
        name = 'foozle'
      )

      dependencies(
        name = 'baz',
      )
      '''
    ))

    with self.assertRaises(AddressLookupError):
      self.address_mapper.resolve_spec('//:bad_spec')

    dependencies_addressable = self.address_mapper.resolve_spec('//:foozle')
    self.assertEqual(dependencies_addressable.target_type, Dependencies)

  def test_raises_address_lookup_error(self):
    # reference a BUILD file that doesn't exist
    self.assertIsInstance(BuildFileAddressMapper.InvalidBuildFileReference(), AddressLookupError)
    with self.assertRaisesRegexp(BuildFileAddressMapper.InvalidBuildFileReference,
                                 '^BUILD file does not exist at: .*/non-existent-path'
                                 '\s+when translating spec //non-existent-path:a'):
      self.address_mapper.spec_to_address('//non-existent-path:a')

    build_file = self.add_to_build_file('BUILD', dedent(
      '''
      dependencies(
        name = 'foo'
      )
      '''
    ))

    # Create an address that doesn't exist in an existing BUILD file
    self.assertIsInstance(BuildFileAddressMapper.AddressNotInBuildFile(), AddressLookupError)
    address = BuildFileAddress(build_file, 'bar')
    with self.assertRaises(BuildFileAddressMapper.AddressNotInBuildFile):
      self.address_mapper.resolve(address)

