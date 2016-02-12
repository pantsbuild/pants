# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import unittest
from contextlib import contextmanager
from textwrap import dedent

from pants.build_graph.address import Address
from pants.engine.exp.mapper import (AddressFamily, AddressMap, AddressMapper,
                                     DifferingFamiliesError, DuplicateNameError, ResolveError,
                                     UnaddressableObjectError)
from pants.engine.exp.parsers import JsonParser, SymbolTable
from pants.engine.exp.struct import Struct
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


class ThingTable(SymbolTable):
  @classmethod
  def table(cls):
    return {'thing': Thing}


class AddressMapTest(unittest.TestCase):
  _parser_cls = JsonParser
  _symbol_table_cls = ThingTable

  @contextmanager
  def parse_address_map(self, json):
    with temporary_file() as fp:
      fp.write(json)
      fp.close()
      address_map = AddressMap.parse(fp.name, self._symbol_table_cls, self._parser_cls)
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


class TargetTable(SymbolTable):
  @classmethod
  def table(cls):
    return {'struct': Struct, 'target': Target}


class AddressMapperTest(unittest.TestCase):
  def setUp(self):
    self.work_dir = safe_mkdtemp()
    self.addCleanup(safe_rmtree, self.work_dir)
    self.build_root = os.path.join(self.work_dir, 'build_root')
    shutil.copytree(os.path.join(os.path.dirname(__file__), 'examples/mapper_test'),
                    self.build_root)

    self.address_mapper = AddressMapper(build_root=self.build_root,
                                        symbol_table_cls=TargetTable,
                                        parser_cls=JsonParser,
                                        build_pattern=r'.+\.BUILD.json$')

    self.a_b_target = Target(name='b',
                             dependencies=['//d:e'],
                             configurations=['//a', Struct(embedded='yes')])

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

  def test_no_address_no_family(self):
    with self.assertRaises(ResolveError):
      self.address_mapper.resolve(Address.parse('a/c'))

    # Errors are not cached.
    with self.assertRaises(ResolveError):
      self.address_mapper.resolve(Address.parse('a/c'))

    build_file = os.path.join(self.build_root, 'a/c/c.BUILD.json')
    with safe_open(build_file, 'w') as fp:
      fp.write('{"type_alias": "struct", "name": "c"}')

    resolved = self.address_mapper.resolve(Address.parse('a/c'))
    self.assertEqual(Struct(name='c'), resolved)

  def test_resolve(self):
    resolved = self.address_mapper.resolve(Address.parse('a/b'))
    self.assertEqual(self.a_b_target, resolved)

  @staticmethod
  def addr(spec):
    return Address.parse(spec)

  def test_walk_addressables(self):
    self.assertEqual(sorted([(self.addr('//:root'), Struct(name='root')),
                             (self.addr('a/b:b'), self.a_b_target),
                             (self.addr('a/d:d'), Target(name='d')),
                             (self.addr('a/d/e:e'), Target(name='e')),
                             (self.addr('a/d/e:e-prime'), Struct(name='e-prime'))]),
                     sorted(self.address_mapper.walk_addressables()))

  def test_walk_addressables_rel_path(self):
    self.assertEqual(sorted([(self.addr('a/d:d'), Target(name='d')),
                             (self.addr('a/d/e:e'), Target(name='e')),
                             (self.addr('a/d/e:e-prime'), Struct(name='e-prime'))]),
                     sorted(self.address_mapper.walk_addressables(rel_path='a/d')))

  def test_walk_addressables_path_excludes(self):
    self.assertEqual([(self.addr('//:root'), Struct(name='root')),
                      (self.addr('a/d:d'), Target(name='d'))],
                     list(self.address_mapper.walk_addressables(path_excludes=['a/b', 'a/d/e'])))
