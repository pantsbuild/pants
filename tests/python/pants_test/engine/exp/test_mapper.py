# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import unittest
from contextlib import contextmanager
from textwrap import dedent

from pants.base.address import Address
from pants.engine.exp import parsers
from pants.engine.exp.mapper import (AddressFamily, AddressMap, DifferingFamiliesError,
                                     DuplicateNameError, UnaddressableObjectError)
from pants.util.contextutil import temporary_file


class Thing(object):
  def __init__(self, **kwargs):
    self._kwargs = kwargs

  def _asdict(self):
    return self._kwargs.copy()

  def _key(self):
    return {k: v for k, v in self._kwargs.items() if k != 'typename'}

  def __eq__(self, other):
    return isinstance(other, Thing) and self._key() == other._key()


class AddressMapTest(unittest.TestCase):
  _parse = functools.partial(parsers.parse_json, symbol_table={'thing': Thing})

  @contextmanager
  def parse_address_map(self, json):
    with temporary_file() as fp:
      fp.write(json)
      fp.close()
      address_map = AddressMap.parse(fp.name, parse=self._parse)
      self.assertEqual(fp.name, address_map.path)
      yield address_map

  def test_parse(self):
    with self.parse_address_map(dedent("""
      {
        "typename": "thing",
        "name": "one",
        "age": 42
      }
      {
        "typename": "thing",
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
      with self.parse_address_map('{"typename": "thing"}'):
        self.fail()

  def test_duplicate_names(self):
    with self.assertRaises(DuplicateNameError):
      with self.parse_address_map('{"typename": "thing", "name": "one"}'
                                  '{"typename": "thing", "name": "one"}'):
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
