# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import os
import shutil
import unittest
from contextlib import contextmanager
from functools import partial
from textwrap import dedent

from pants.build_graph.address import Address
from pants.engine.exp import parsers
from pants.engine.exp.configuration import Configuration
from pants.engine.exp.mapper import (AddressFamily, AddressMap, AddressMapper,
                                     DifferingFamiliesError, DuplicateNameError, ResolveError,
                                     UnaddressableObjectError)
from pants.engine.exp.parsers import parse_json
from pants.engine.exp.targets import Target
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_mkdtemp, safe_open, safe_rmtree, touch


class Thing(object):
  def __init__(self, **kwargs):
    self._kwargs = kwargs

  def _asdict(self):
    return self._kwargs

  def _key(self):
    return {k: v for k, v in self._kwargs.items() if k != 'type_alias'}

  def __eq__(self, other):
    return isinstance(other, Thing) and self._key() == other._key()


class AddressMapTest(unittest.TestCase):
  _parser = functools.partial(parsers.parse_json, symbol_table={'thing': Thing})

  @contextmanager
  def parse_address_map(self, json):
    with temporary_file() as fp:
      fp.write(json)
      fp.close()
      address_map = AddressMap.parse(fp.name, parser=self._parser)
      self.assertEqual(fp.name, address_map.path)
      yield address_map

  def test_parse(self):
    with self.parse_address_map(dedent("""
      {
        "type_alias": "thing",
        "name": "one",
        "age": 42
      }
      {
        "type_alias": "thing",
        "name": "two",
        "age": 37
      }
      """)) as address_map:

      self.assertEqual({'one': Thing(name='one', age=42), 'two': Thing(name='two', age=37)},
                       address_map.objects_by_name)

  def test_not_serializable(self):
    with self.assertRaises(UnaddressableObjectError):
      with self.parse_address_map('{}'):
        self.fail()

  def test_not_named(self):
    with self.assertRaises(UnaddressableObjectError):
      with self.parse_address_map('{"type_alias": "thing"}'):
        self.fail()

  def test_duplicate_names(self):
    with self.assertRaises(DuplicateNameError):
      with self.parse_address_map('{"type_alias": "thing", "name": "one"}'
                                  '{"type_alias": "thing", "name": "one"}'):
        self.fail()


class AddressFamilyTest(unittest.TestCase):
  def test_create_single(self):
    address_family = AddressFamily.create('/dev/null',
                                          [AddressMap('/dev/null/0', {
                                            'one': Thing(name='one', age=42),
                                            'two': Thing(name='two', age=37)
                                          })])
    self.assertEqual('', address_family.namespace)
    self.assertEqual({Address.parse('//:one'): Thing(name='one', age=42),
                      Address.parse('//:two'): Thing(name='two', age=37)},
                     address_family.addressables)

  def test_create_multiple(self):
    address_family = AddressFamily.create('/dev/null',
                                          [AddressMap('/dev/null/name/space/0',
                                                      {'one': Thing(name='one', age=42)}),
                                           AddressMap('/dev/null/name/space/1',
                                                      {'two': Thing(name='two', age=37)})])

    self.assertEqual('name/space', address_family.namespace)
    self.assertEqual({Address.parse('name/space:one'): Thing(name='one', age=42),
                      Address.parse('name/space:two'): Thing(name='two', age=37)},
                     address_family.addressables)

  def test_mismatching_paths(self):
    with self.assertRaises(DifferingFamiliesError):
      AddressFamily.create('/dev/null', [AddressMap('/dev/null/one/0', {}),
                                         AddressMap('/dev/null/two/0', {})])

  def test_duplicate_names(self):
    with self.assertRaises(DuplicateNameError):
      AddressFamily.create('/dev/null', [AddressMap('/dev/null/name/space/0',
                                                    {'one': Thing(name='one', age=42)}),
                                         AddressMap('/dev/null/name/space/1',
                                                    {'one': Thing(name='one', age=37)})])


class AddressMapperTest(unittest.TestCase):
  def setUp(self):
    self.work_dir = safe_mkdtemp()
    self.addCleanup(safe_rmtree, self.work_dir)
    self.build_root = os.path.join(self.work_dir, 'build_root')
    shutil.copytree(os.path.join(os.path.dirname(__file__), 'examples/mapper_test'),
                    self.build_root)

    parser = partial(parse_json, symbol_table={'configuration': Configuration, 'target': Target})
    self.address_mapper = AddressMapper(build_root=self.build_root,
                                        build_pattern=r'.+\.BUILD.json$',
                                        parser=parser)

    self.a_b_target = Target(name='b',
                             dependencies=['//d:e'],
                             configurations=['//a', Configuration(embedded='yes')])

  def test_no_family(self):
    with self.assertRaises(ResolveError):
      self.address_mapper.family('a/c')

    # Errors are not cached.
    with self.assertRaises(ResolveError):
      self.address_mapper.family('a/c')

    build_file = os.path.join(self.build_root, 'a/c/c.BUILD.json')
    touch(build_file)
    address_family = self.address_mapper.family('a/c')
    self.assertEqual({}, address_family.addressables)

    # But success is cached.
    self.assertIs(address_family, self.address_mapper.family('a/c'))

  def test_no_address_no_family(self):
    with self.assertRaises(ResolveError):
      self.address_mapper.resolve(Address.parse('a/c'))

    # Errors are not cached.
    with self.assertRaises(ResolveError):
      self.address_mapper.resolve(Address.parse('a/c'))

    build_file = os.path.join(self.build_root, 'a/c/c.BUILD.json')
    with safe_open(build_file, 'w') as fp:
      fp.write('{"type_alias": "configuration", "name": "c"}')

    resolved = self.address_mapper.resolve(Address.parse('a/c'))
    self.assertEqual(Configuration(name='c'), resolved)

    # But success is cached.
    self.assertIs(resolved, self.address_mapper.resolve(Address.parse('a/c')))

  def test_resolve(self):
    resolved = self.address_mapper.resolve(Address.parse('a/b'))
    self.assertEqual(self.a_b_target, resolved)

  def test_invalidate_build_file_added(self):
    address_family = self.address_mapper.family('a/b')

    self.assertEqual({Address.parse('a/b'): self.a_b_target},
                     address_family.addressables)

    with open(os.path.join(self.build_root, 'a/b/sibling.BUILD.json'), 'w') as fp:
      fp.write('{"type_alias": "configuration", "name": "c"}')

    still_valid = self.address_mapper.family('a/b')
    self.assertIs(address_family, still_valid)

    self.address_mapper.invalidate_build_file('a/b/sibling.BUILD.json')
    newly_formed = self.address_mapper.family('a/b')
    self.assertIsNot(address_family, newly_formed)
    self.assertEqual({Address.parse('a/b'): self.a_b_target,
                      Address.parse('a/b:c'): Configuration(name='c')},
                     newly_formed.addressables)

  def test_invalidate_build_file_changed(self):
    with self.assertRaises(ResolveError):
      self.address_mapper.resolve(Address.parse('a/b:c'))

    build_file = os.path.join(self.build_root, 'a/b/b.BUILD.json')
    with safe_open(build_file, 'w+') as fp:
      fp.write('{"type_alias": "configuration", "name": "c"}')

    with self.assertRaises(ResolveError):
      self.address_mapper.resolve(Address.parse('a/b:c'))

    self.address_mapper.invalidate_build_file('a/b/b.BUILD.json')
    resolved = self.address_mapper.resolve(Address.parse('a/b:c'))
    self.assertEqual(Configuration(name='c'), resolved)

    # But success is cached.
    self.assertIs(resolved, self.address_mapper.resolve(Address.parse('a/b:c')))

  def test_invalidate_build_file_removed(self):
    resolved = self.address_mapper.resolve(Address.parse('a/b'))
    self.assertEqual(self.a_b_target, resolved)

    build_file = os.path.join(self.build_root, 'a/b/b.BUILD.json')
    os.unlink(build_file)
    self.assertIs(resolved, self.address_mapper.resolve(Address.parse('a/b')))

    self.address_mapper.invalidate_build_file(build_file)
    with self.assertRaises(ResolveError):
      self.address_mapper.resolve(Address.parse('a/b'))

  def test_invalidation_un_normalized(self):
    resolved = self.address_mapper.resolve(Address.parse('a/b'))
    self.assertEqual(self.a_b_target, resolved)

    os.unlink(os.path.join(self.build_root, 'a/b/b.BUILD.json'))
    self.assertIs(resolved, self.address_mapper.resolve(Address.parse('a/b')))

    un_normalized_build_root = os.path.join(self.work_dir, 'build_root_linked')
    os.symlink(self.build_root, un_normalized_build_root)
    un_normalized_build_file = os.path.join(un_normalized_build_root, 'a/b/b.BUILD.json')
    self.address_mapper.invalidate_build_file(un_normalized_build_file)
    with self.assertRaises(ResolveError):
      self.address_mapper.resolve(Address.parse('a/b'))

  def test_invalidation_relative(self):
    resolved = self.address_mapper.resolve(Address.parse('a/b'))
    self.assertEqual(self.a_b_target, resolved)

    build_file = os.path.join(self.build_root, 'a/b/b.BUILD.json')
    os.unlink(build_file)
    self.assertIs(resolved, self.address_mapper.resolve(Address.parse('a/b')))

    self.address_mapper.invalidate_build_file('a/b/b.BUILD.json')
    with self.assertRaises(ResolveError):
      self.address_mapper.resolve(Address.parse('a/b'))

  @staticmethod
  def addr(spec):
    return Address.parse(spec)

  def test_walk_addressables(self):
    self.assertEqual(sorted([(self.addr('//:root'), Configuration(name='root')),
                             (self.addr('a/b:b'), self.a_b_target),
                             (self.addr('a/d:d'), Target(name='d')),
                             (self.addr('a/d/e:e'), Target(name='e')),
                             (self.addr('a/d/e:e-prime'), Configuration(name='e-prime'))]),
                     sorted(self.address_mapper.walk_addressables()))

  def test_walk_addressables_rel_path(self):
    self.assertEqual(sorted([(self.addr('a/d:d'), Target(name='d')),
                             (self.addr('a/d/e:e'), Target(name='e')),
                             (self.addr('a/d/e:e-prime'), Configuration(name='e-prime'))]),
                     sorted(self.address_mapper.walk_addressables(rel_path='a/d')))

  def test_walk_addressables_path_excludes(self):
    self.assertEqual([(self.addr('//:root'), Configuration(name='root')),
                      (self.addr('a/d:d'), Target(name='d'))],
                     list(self.address_mapper.walk_addressables(path_excludes=['a/b', 'a/d/e'])))
