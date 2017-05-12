# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import unittest
from contextlib import contextmanager
from textwrap import dedent

from pants.base.specs import DescendantAddresses, SiblingAddresses, SingleAddress
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses, Collection
from pants.engine.build_files import UnhydratedStruct, create_graph_rules
from pants.engine.engine import LocalSerialEngine
from pants.engine.mapper import (AddressFamily, AddressMap, AddressMapper, DifferingFamiliesError,
                                 DuplicateNameError, UnaddressableObjectError)
from pants.engine.nodes import Throw
from pants.engine.parser import SymbolTable
from pants.engine.rules import TaskRule
from pants.engine.selectors import Select, SelectDependencies
from pants.engine.struct import Struct
from pants.util.dirutil import safe_open
from pants_test.engine.examples.parsers import JsonParser
from pants_test.engine.scheduler_test_base import SchedulerTestBase
from pants_test.engine.util import Target, TargetTable


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
    path = '/dev/null'
    address_map = AddressMap.parse(path, json, self._symbol_table_cls, self._parser_cls)
    self.assertEqual(path, address_map.path)
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
    address_family = AddressFamily.create('',
                                          [AddressMap('0', {
                                            'one': Thing(name='one', age=42),
                                            'two': Thing(name='two', age=37)
                                          })])
    self.assertEqual('', address_family.namespace)
    self.assertEqual({Address.parse('//:one'): Thing(name='one', age=42),
                      Address.parse('//:two'): Thing(name='two', age=37)},
                     address_family.addressables)

  def test_create_multiple(self):
    address_family = AddressFamily.create('name/space',
                                          [AddressMap('name/space/0',
                                                      {'one': Thing(name='one', age=42)}),
                                           AddressMap('name/space/1',
                                                      {'two': Thing(name='two', age=37)})])

    self.assertEqual('name/space', address_family.namespace)
    self.assertEqual({Address.parse('name/space:one'): Thing(name='one', age=42),
                      Address.parse('name/space:two'): Thing(name='two', age=37)},
                     address_family.addressables)

  def test_create_empty(self):
    # Case where directory exists but is empty.
    address_family = AddressFamily.create('name/space', [])
    self.assertEquals(dict(), address_family.addressables)

  def test_mismatching_paths(self):
    with self.assertRaises(DifferingFamiliesError):
      AddressFamily.create('one',
                           [AddressMap('/dev/null/one/0', {}),
                            AddressMap('/dev/null/two/0', {})])

  def test_duplicate_names(self):
    with self.assertRaises(DuplicateNameError):
      AddressFamily.create('name/space',
                           [AddressMap('name/space/0',
                                       {'one': Thing(name='one', age=42)}),
                            AddressMap('name/space/1',
                                       {'one': Thing(name='one', age=37)})])


UnhydratedStructs = Collection.of(UnhydratedStruct)


class AddressMapperTest(unittest.TestCase, SchedulerTestBase):
  def setUp(self):
    # Set up a scheduler that supports address mapping.
    symbol_table_cls = TargetTable
    address_mapper = AddressMapper(symbol_table_cls=symbol_table_cls,
                                   parser_cls=JsonParser,
                                   build_patterns=('*.BUILD.json',))
    tasks = create_graph_rules(address_mapper, symbol_table_cls)
    # TODO handle updating the rule graph when passed unexpected root selectors.
    # Adding the following task allows us to get around the fact that SelectDependencies
    # requests are not currently supported.
    tasks.append(TaskRule(UnhydratedStructs,
                          [SelectDependencies(UnhydratedStruct,
                                              BuildFileAddresses,
                                              field_types=(Address,),
                                              field='addresses')],
                          UnhydratedStructs))

    project_tree = self.mk_fs_tree(os.path.join(os.path.dirname(__file__), 'examples/mapper_test'))
    self.build_root = project_tree.build_root
    self.scheduler = self.mk_scheduler(tasks=tasks, project_tree=project_tree)

    self.a_b = Address.parse('a/b')
    self.a_b_target = Target(name='b',
                             dependencies=['//d:e'],
                             configurations=['//a', Struct(embedded='yes')],
                             type_alias='target')

  def resolve(self, spec):
    # TODO reenable using SelectDependencies
    select = Select(UnhydratedStructs)
    request = self.scheduler.selection_request([(select, spec)])
    result = LocalSerialEngine(self.scheduler).execute(request)
    if result.error:
      raise result.error

    # Expect a single root.
    state, = result.root_products.values()
    if type(state) is Throw:
      raise Exception(state.exc)
    return state.value.dependencies

  def resolve_multi(self, spec):
    return {uhs.address: uhs.struct for uhs in self.resolve(spec)}

  def test_no_address_no_family(self):
    spec = SingleAddress('a/c', 'c')

    # Does not exist.
    with self.assertRaises(Exception):
      self.resolve(spec)

    build_file = os.path.join(self.build_root, 'a/c', 'c.BUILD.json')
    with safe_open(build_file, 'w') as fp:
      fp.write('{"type_alias": "struct", "name": "c"}')

    # Exists on disk, but not yet in memory.
    with self.assertRaises(Exception):
      self.resolve(spec)

    self.scheduler.invalidate_files(['a/c'])

    # Success.
    resolved = self.resolve(spec)
    self.assertEqual(1, len(resolved))
    self.assertEqual([Struct(name='c', type_alias='struct')], [r.struct for r in resolved])

  def test_resolve(self):
    resolved = self.resolve(SingleAddress('a/b', 'b'))
    self.assertEqual(1, len(resolved))
    self.assertEqual(self.a_b, resolved[0].address)

  @staticmethod
  def addr(spec):
    return Address.parse(spec)

  def test_walk_siblings(self):
    self.assertEqual({self.addr('a/b:b'): self.a_b_target},
                     self.resolve_multi(SiblingAddresses('a/b')))

  def test_walk_descendants(self):
    self.assertEqual({self.addr('//:root'): Struct(name='root', type_alias='struct'),
                      self.addr('a/b:b'): self.a_b_target,
                      self.addr('a/d:d'): Target(name='d', type_alias='target'),
                      self.addr('a/d/e:e'): Target(name='e', type_alias='target'),
                      self.addr('a/d/e:e-prime'): Struct(name='e-prime', type_alias='struct')},
                     self.resolve_multi(DescendantAddresses('')))

  def test_walk_descendants_rel_path(self):
    self.assertEqual({self.addr('a/d:d'): Target(name='d', type_alias='target'),
                      self.addr('a/d/e:e'): Target(name='e', type_alias='target'),
                      self.addr('a/d/e:e-prime'): Struct(name='e-prime', type_alias='struct')},
                     self.resolve_multi(DescendantAddresses('a/d')))
