# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from textwrap import dedent

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.specs import DescendantAddresses
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
                                 '^.*/non-existent-path does not contain any BUILD files.'
                                 '\s+when translating spec //non-existent-path:a'):
      self.address_mapper.spec_to_address('//non-existent-path:a')
    with self.assertRaisesRegexp(BuildFileAddressMapper.InvalidBuildFileReference,
                                 '^Spec : has no name part\s+when translating spec :'):
      self.address_mapper.spec_to_address(':')

  def test_raises_address_not_in_one_build_file(self):
    self.add_to_build_file('BUILD', 'target(name="foo")')

    # Create an address that doesn't exist in an existing BUILD file
    address = Address.parse(':bar')
    with self.assertRaisesRegexp(BuildFileAddressMapper.AddressNotInBuildFile,
                                 '^bar was not found in BUILD files from .*. '
                                 'Perhaps you meant:'
                                 '\s+:foo$'):
      self.address_mapper.resolve(address)

  def test_raises_address_not_in_two_build_files(self):
    self.add_to_build_file('BUILD.1', 'target(name="foo1")')
    self.add_to_build_file('BUILD.2', 'target(name="foo2")')

    # Create an address that doesn't exist in an existing BUILD file
    address = Address.parse(':bar')
    with self.assertRaisesRegexp(BuildFileAddressMapper.AddressNotInBuildFile,
                                 '^bar was not found in BUILD files from .*. '
                                 'Perhaps you meant one of:'
                                 '\s+:foo1 \(from BUILD.1\)'
                                 '\s+:foo2 \(from BUILD.2\)$'):
      self.address_mapper.resolve(address)

  def test_raises_address_invalid_address_error(self):
    with self.assertRaises(BuildFileAddressMapper.InvalidAddressError):
      self.address_mapper.resolve_spec("../foo")

  def test_raises_empty_build_file_error(self):
    self.add_to_build_file('BUILD', 'pass')
    with self.assertRaises(BuildFileAddressMapper.EmptyBuildFileError):
      self.address_mapper.resolve_spec('//:foo')

  def test_address_lookup_error_hierarchy(self):
    self.assertIsInstance(BuildFileAddressMapper.AddressNotInBuildFile(), AddressLookupError)
    self.assertIsInstance(BuildFileAddressMapper.EmptyBuildFileError(), AddressLookupError)
    self.assertIsInstance(BuildFileAddressMapper.InvalidBuildFileReference(), AddressLookupError)
    self.assertIsInstance(BuildFileAddressMapper.InvalidAddressError(), AddressLookupError)
    self.assertIsInstance(BuildFileAddressMapper.BuildFileScanError(), AddressLookupError)

  def test_raises_wrong_dependencies_type(self):
    self.add_to_build_file('BUILD', 'target(name="foo", dependencies="bar")')
    address = Address.parse(':foo')
    with self.assertRaisesRegexp(AddressLookupError,
                                 '^Invalid target.*foo.*.'
                                 'dependencies passed to Target constructors must be a sequence of strings'):
      self.address_mapper.resolve(address)


class BuildFileAddressMapperWithIgnoreTest(BaseTest):
  @property
  def build_ignore_patterns(self):
    return ['subdir']

  def test_scan_from_address_mapper(self):
    root_build_file = self.add_to_build_file('BUILD', 'target(name="foo")')
    self.add_to_build_file('subdir/BUILD', 'target(name="bar")')
    self.assertEquals({BuildFileAddress(root_build_file, 'foo')}, self.address_mapper.scan_addresses())

  def test_scan_from_context(self):
    self.add_to_build_file('BUILD', 'target(name="foo")')
    self.add_to_build_file('subdir/BUILD', 'target(name="bar")')
    graph = self.context().scan()
    self.assertEquals([target.address.spec for target in graph.targets()], ['//:foo'])


class BuildFileAddressMapperScanTest(BaseTest):

  NO_FAIL_FAST_RE = re.compile(r"""^--------------------
.*
Exception message: name 'a_is_bad' is not defined
 while executing BUILD file BuildFile\(bad/a/BUILD, FileSystemProjectTree\(.*\)\)
 Loading addresses from 'bad/a' failed\.
.*
Exception message: name 'b_is_bad' is not defined
 while executing BUILD file BuildFile\(bad/b/BUILD, FileSystemProjectTree\(.*\)\)
 Loading addresses from 'bad/b' failed\.
Invalid BUILD files for \[::\]$""", re.DOTALL)

  FAIL_FAST_RE = """^name 'a_is_bad' is not defined
 while executing BUILD file BuildFile\(bad/a/BUILD\, FileSystemProjectTree\(.*\)\)
 Loading addresses from 'bad/a' failed.$"""

  def setUp(self):
    super(BuildFileAddressMapperScanTest, self).setUp()

    def add_target(path, name):
      self.add_to_build_file(path, 'target(name="{name}")\n'.format(name=name))

    add_target('BUILD', 'root')
    add_target('a', 'a')
    add_target('a', 'b')
    add_target('a/b', 'b')
    add_target('a/b', 'c')

    self._spec_parser = CmdLineSpecParser(self.build_root)

  def test_bad_build_files(self):
    self.add_to_build_file('bad/a', 'a_is_bad')
    self.add_to_build_file('bad/b', 'b_is_bad')

    with self.assertRaisesRegexp(AddressLookupError, self.NO_FAIL_FAST_RE):
      list(self.address_mapper.scan_specs([DescendantAddresses('')], fail_fast=False))

  def test_bad_build_files_fail_fast(self):
    self.add_to_build_file('bad/a', 'a_is_bad')
    self.add_to_build_file('bad/b', 'b_is_bad')

    with self.assertRaisesRegexp(AddressLookupError, self.FAIL_FAST_RE):
      list(self.address_mapper.scan_specs([DescendantAddresses('')], fail_fast=True))

  def test_normal(self):
    self.assert_scanned([':root'], expected=[':root'])
    self.assert_scanned(['//:root'], expected=[':root'])

    self.assert_scanned(['a'], expected=['a'])
    self.assert_scanned(['a:a'], expected=['a'])

    self.assert_scanned(['a/b'], expected=['a/b'])
    self.assert_scanned(['a/b:b'], expected=['a/b'])
    self.assert_scanned(['a/b:c'], expected=['a/b:c'])

  def test_sibling(self):
    self.assert_scanned([':'], expected=[':root'])
    self.assert_scanned(['//:'], expected=[':root'])

    self.assert_scanned(['a:'], expected=['a', 'a:b'])
    self.assert_scanned(['//a:'], expected=['a', 'a:b'])

    self.assert_scanned(['a/b:'], expected=['a/b', 'a/b:c'])
    self.assert_scanned(['//a/b:'], expected=['a/b', 'a/b:c'])

  def test_sibling_or_descendents(self):
    self.assert_scanned(['::'], expected=[':root', 'a', 'a:b', 'a/b', 'a/b:c'])
    self.assert_scanned(['//::'], expected=[':root', 'a', 'a:b', 'a/b', 'a/b:c'])

    self.assert_scanned(['a::'], expected=['a', 'a:b', 'a/b', 'a/b:c'])
    self.assert_scanned(['//a::'], expected=['a', 'a:b', 'a/b', 'a/b:c'])

    self.assert_scanned(['a/b::'], expected=['a/b', 'a/b:c'])
    self.assert_scanned(['//a/b::'], expected=['a/b', 'a/b:c'])

  def test_cmd_line_affordances(self):
    self.assert_scanned(['./:root'], expected=[':root'])
    self.assert_scanned(['//./:root'], expected=[':root'])
    self.assert_scanned(['//./a/../:root'], expected=[':root'])
    self.assert_scanned([os.path.join(self.build_root, './a/../:root')],
                       expected=[':root'])

    self.assert_scanned(['a/'], expected=['a'])
    self.assert_scanned(['./a/'], expected=['a'])
    self.assert_scanned([os.path.join(self.build_root, './a/')], expected=['a'])

    self.assert_scanned(['a/b/:b'], expected=['a/b'])
    self.assert_scanned(['./a/b/:b'], expected=['a/b'])
    self.assert_scanned([os.path.join(self.build_root, './a/b/:b')], expected=['a/b'])

  def test_cmd_line_spec_list(self):
    self.assert_scanned(['a', 'a/b'], expected=['a', 'a/b'])
    self.assert_scanned(['::'], expected=[':root', 'a', 'a:b', 'a/b', 'a/b:c'])

  def test_does_not_exist(self):
    with self.assertRaises(AddressLookupError):
      self.assert_scanned(['c'], expected=[])

    with self.assertRaises(AddressLookupError):
      self.assert_scanned(['c:'], expected=[])

    with self.assertRaises(AddressLookupError):
      self.assert_scanned(['c::'], expected=[])

  def test_build_ignore_patterns(self):
    expected_specs = [':root', 'a', 'a:b', 'a/b', 'a/b:c']

    # This bogus BUILD file gets in the way of parsing.
    self.add_to_build_file('some/dir', 'COMPLETELY BOGUS BUILDFILE)\n')
    with self.assertRaises(AddressLookupError):
      self.assert_scanned(['::'], expected=expected_specs)

    address_mapper_with_ignore = BuildFileAddressMapper(self.build_file_parser,
                                                        self.project_tree,
                                                        build_ignore_patterns=['some'])
    self.assert_scanned(['::'], expected=expected_specs, address_mapper=address_mapper_with_ignore)

  def test_exclude_target_regexps(self):
    address_mapper_with_exclude = BuildFileAddressMapper(self.build_file_parser,
                                                         self.project_tree,
                                                         exclude_target_regexps=[r'.*:b.*'])
    self.assert_scanned(['::'], expected=[':root', 'a', 'a/b:c'],
                        address_mapper=address_mapper_with_exclude)

  def assert_scanned(self, specs_strings, expected, address_mapper=None):
    """Parse and scan the given specs."""
    address_mapper = address_mapper or self.address_mapper

    def sort(addresses):
      return sorted(addresses, key=lambda address: address.spec)

    specs = [self._spec_parser.parse_spec(s) for s in specs_strings]

    self.assertEqual(sort(Address.parse(addr) for addr in expected),
                     sort(address_mapper.scan_specs(specs)))
