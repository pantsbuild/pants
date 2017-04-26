# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

import mock

from pants.base.specs import SiblingAddresses, SingleAddress
from pants.bin.engine_initializer import EngineInitializer
from pants.build_graph.address import Address, BuildFileAddress
from pants.build_graph.address_mapper import AddressMapper
from pants.engine.engine import Engine
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.nodes import Throw
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_file_dump, safe_mkdir
from pants_test.engine.util import init_native


class LegacyAddressMapperTest(unittest.TestCase):

  _native = init_native()

  def create_build_files(self, build_root):
    # Create BUILD files
    # build_root:
    #   BUILD
    #   BUILD.other
    #   dir_a:
    #     BUILD
    #     BUILD.other
    #     subdir:
    #       BUILD
    #   dir_b:
    #     BUILD
    dir_a = os.path.join(build_root, 'dir_a')
    dir_b = os.path.join(build_root, 'dir_b')
    dir_a_subdir = os.path.join(dir_a, 'subdir')
    safe_mkdir(dir_a)
    safe_mkdir(dir_b)
    safe_mkdir(dir_a_subdir)

    safe_file_dump(os.path.join(build_root, 'BUILD'), 'target(name="a")\ntarget(name="b")')
    safe_file_dump(os.path.join(build_root, 'BUILD.other'), 'target(name="c")')

    safe_file_dump(os.path.join(dir_a, 'BUILD'), 'target(name="a")\ntarget(name="b")')
    safe_file_dump(os.path.join(dir_a, 'BUILD.other'), 'target(name="c")')

    safe_file_dump(os.path.join(dir_b, 'BUILD'), 'target(name="a")')

    safe_file_dump(os.path.join(dir_a_subdir, 'BUILD'), 'target(name="a")')

  def create_address_mapper(self, build_root):
    work_dir = os.path.join(build_root, '.pants.d')
    scheduler, engine, _, _ = EngineInitializer.setup_legacy_graph(
      [],
      work_dir,
      build_root=build_root,
      native=self._native
    )
    return LegacyAddressMapper(scheduler, engine, build_root)

  def test_is_valid_single_address(self):
    with temporary_dir() as build_root:
      self.create_build_files(build_root)
      mapper = self.create_address_mapper(build_root)

      self.assertFalse(mapper.is_valid_single_address(SingleAddress('dir_a', 'foo')))
      self.assertTrue(mapper.is_valid_single_address(SingleAddress('dir_a', 'a')))
      with self.assertRaises(TypeError):
        mapper.is_valid_single_address('foo')

  def test_scan_build_files(self):
    with temporary_dir() as build_root:
      self.create_build_files(build_root)
      mapper = self.create_address_mapper(build_root)

      build_files = mapper.scan_build_files('')
      self.assertEqual(build_files,
                       {'BUILD', 'BUILD.other',
                        'dir_a/BUILD', 'dir_a/BUILD.other',
                        'dir_b/BUILD', 'dir_a/subdir/BUILD'})

      build_files = mapper.scan_build_files('dir_a/subdir')
      self.assertEqual(build_files, {'dir_a/subdir/BUILD'})

  def test_scan_build_files_edge_cases(self):
    with temporary_dir() as build_root:
      self.create_build_files(build_root)
      mapper = self.create_address_mapper(build_root)

      # A non-existent dir.
      build_files = mapper.scan_build_files('foo')
      self.assertEqual(build_files, set())

      # A dir with no BUILD files.
      safe_mkdir(os.path.join(build_root, 'empty'))
      build_files = mapper.scan_build_files('empty')
      self.assertEqual(build_files, set())

  def test_is_declaring_file(self):
    scheduler = mock.Mock()
    mapper = LegacyAddressMapper(scheduler, None, '')
    self.assertTrue(mapper.is_declaring_file(Address('path', 'name'), 'path/BUILD'))
    self.assertTrue(mapper.is_declaring_file(Address('path', 'name'), 'path/BUILD.suffix'))
    self.assertFalse(mapper.is_declaring_file(Address('path', 'name'), 'path/not_a_build_file'))
    self.assertFalse(mapper.is_declaring_file(Address('path', 'name'), 'differing-path/BUILD'))
    self.assertFalse(mapper.is_declaring_file(
      BuildFileAddress(target_name='name', rel_path='path/BUILD.new'),
      'path/BUILD'))
    self.assertTrue(mapper.is_declaring_file(
      BuildFileAddress(target_name='name', rel_path='path/BUILD'),
      'path/BUILD'))

  def test_addresses_in_spec_path(self):
    with temporary_dir() as build_root:
      self.create_build_files(build_root)
      mapper = self.create_address_mapper(build_root)
      addresses = mapper.addresses_in_spec_path('dir_a')
      self.assertEqual(addresses,
                       {Address('dir_a', 'a'), Address('dir_a', 'b'), Address('dir_a', 'c')})

  def test_addresses_in_spec_path_no_dir(self):
    with temporary_dir() as build_root:
      self.create_build_files(build_root)
      mapper = self.create_address_mapper(build_root)
      with self.assertRaises(AddressMapper.BuildFileScanError) as cm:
        mapper.addresses_in_spec_path('foo')
      self.assertIn('does not match any targets.', str(cm.exception))

  def test_addresses_in_spec_path_no_build_files(self):
    with temporary_dir() as build_root:
      self.create_build_files(build_root)
      safe_mkdir(os.path.join(build_root, 'foo'))
      mapper = self.create_address_mapper(build_root)
      with self.assertRaises(AddressMapper.BuildFileScanError) as cm:
        mapper.addresses_in_spec_path('foo')
      self.assertIn('does not match any targets.', str(cm.exception))

  def test_scan_specs(self):
    with temporary_dir() as build_root:
      self.create_build_files(build_root)
      mapper = self.create_address_mapper(build_root)
      addresses = mapper.scan_specs([SingleAddress('dir_a', 'a'), SiblingAddresses('')])
      self.assertEqual(addresses,
                       {Address('', 'a'), Address('', 'b'), Address('', 'c'), Address('dir_a', 'a')})

  def test_scan_specs_bad_spec(self):
    with temporary_dir() as build_root:
      self.create_build_files(build_root)
      mapper = self.create_address_mapper(build_root)
      with self.assertRaises(AddressMapper.BuildFileScanError) as cm:
        mapper.scan_specs([SingleAddress('dir_a', 'd')])
      self.assertIn('does not match any targets.', str(cm.exception))

  def test_scan_addresses(self):
    with temporary_dir() as build_root:
      self.create_build_files(build_root)
      mapper = self.create_address_mapper(build_root)
      addresses = mapper.scan_addresses()
      self.assertEqual(addresses,
                       {Address('', 'a'), Address('', 'b'), Address('', 'c'),
                        Address('dir_a', 'a'), Address('dir_a', 'b'), Address('dir_a', 'c'),
                        Address('dir_b', 'a'), Address('dir_a/subdir', 'a')})

  def test_scan_addresses_with_root_specified(self):
    with temporary_dir() as build_root:
      self.create_build_files(build_root)
      mapper = self.create_address_mapper(build_root)
      addresses = mapper.scan_addresses(os.path.join(build_root, 'dir_a'))
      self.assertEqual(addresses,
                       {Address('dir_a', 'a'), Address('dir_a', 'b'), Address('dir_a', 'c'),
                        Address('dir_a/subdir', 'a')})

  def test_scan_addresses_bad_dir(self):
    # scan_addresses() should not raise an error.
    with temporary_dir() as build_root:
      self.create_build_files(build_root)
      mapper = self.create_address_mapper(build_root)
      addresses = mapper.scan_addresses(os.path.join(build_root, 'foo'))
      self.assertEqual(addresses, set())

  def test_other_throw_is_fail(self):
    # scan_addresses() should raise an error if the scheduler returns an error it can't ignore.
    class ThrowReturningScheduler(object):
      def execution_request(self, *args):
        pass

    class ThrowResultingEngine(object):
      def execute(self, *args):
        return Engine.Result(None, {('some-thing', None): Throw(Exception('just an exception'))})

    with temporary_dir() as build_root:
      mapper = LegacyAddressMapper(ThrowReturningScheduler(), ThrowResultingEngine(), build_root)

      with self.assertRaises(LegacyAddressMapper.BuildFileScanError) as cm:
        mapper.scan_addresses(os.path.join(build_root, 'foo'))
      self.assertIn('just an exception', str(cm.exception))
