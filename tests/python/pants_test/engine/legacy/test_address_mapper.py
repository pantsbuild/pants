# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import mock
from twitter.common.collections import OrderedSet

from pants.base.specs import DescendantAddresses, SiblingAddresses
from pants.build_graph.address import Address
from pants.build_graph.address_mapper import AddressMapper
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.graph import LegacyBuildGraph, LegacyTarget


class LegacyAddressMapperTest(unittest.TestCase):

  def test_addresses_in_spec_path_wraps_error_in_buildfile_scan_error(self):
    graph_mock = mock.Mock()
    graph_mock.inject_specs_closure = mock.Mock(side_effect=LegacyBuildGraph.InvalidCommandLineSpecError('some msg'))

    mapper = LegacyAddressMapper(graph_mock, '')
    with self.assertRaises(AddressMapper.BuildFileScanError) as cm:
      mapper.addresses_in_spec_path('some/path')
    self.assertEqual('some msg', str(cm.exception))

  def test_scan_specs_returns_ordered_set(self):
    address = Address('a', 'b')

    graph_mock = mock.Mock()
    graph_mock.inject_specs_closure = mock.Mock(return_value=[address, address])

    mapper = LegacyAddressMapper(graph_mock, '')
    self.assertEqual(OrderedSet([address]), mapper.scan_specs([SiblingAddresses('any')]))

  def test_scan_addresses_with_root_specified(self):
    address = Address('a', 'b')

    graph_mock = mock.Mock()
    graph_mock.inject_specs_closure = mock.Mock(return_value=[address])

    mapper = LegacyAddressMapper(graph_mock, '/some/build/root')
    absolute_root_path = '/some/build/root/a'
    mapper.scan_addresses(absolute_root_path)

    graph_mock.inject_specs_closure.assert_called_with([DescendantAddresses('a')])

  def test_resolve_with_a_target(self):
    target = LegacyTarget(None, None)
    address = Address('a', 'a')

    graph_mock = mock.Mock()
    graph_mock.get_target = mock.Mock(return_value=target)

    mapper = LegacyAddressMapper(graph_mock, '')
    self.assertEqual((address, target), mapper.resolve(address))

  def test_resolve_without_a_matching_target(self):
    graph_mock = mock.Mock()
    graph_mock.get_target = mock.Mock(return_value=None)
    graph_mock.inject_specs_closure = mock.Mock(return_value=[Address('a','different')])

    mapper = LegacyAddressMapper(graph_mock, '')
    with self.assertRaises(AddressMapper.BuildFileScanError):
      mapper.resolve(Address('a', 'address'))

  def test_is_declaring_file(self):
    mapper = LegacyAddressMapper(None, '')
    self.assertTrue(mapper.is_declaring_file(Address('path', 'name'), 'path/BUILD'))
    self.assertTrue(mapper.is_declaring_file(Address('path', 'name'), 'path/BUILD.suffix'))
    self.assertFalse(mapper.is_declaring_file(Address('path', 'name'), 'path/not_a_build_file'))
    self.assertFalse(mapper.is_declaring_file(Address('path', 'name'), 'differing-path/BUILD'))
