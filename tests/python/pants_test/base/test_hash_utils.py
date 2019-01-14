# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import hashlib
import json
import math
import unittest
from builtins import range, str
from collections import OrderedDict

from future.utils import PY3

from pants.base.hash_utils import CoercingEncoder, Sharder, hash_all, hash_file, stable_json_sha1
from pants.util.contextutil import temporary_file


class TestHashUtils(unittest.TestCase):

  def test_hash_all(self):
    expected_hash = hashlib.md5()
    expected_hash.update(b'jakejones')
    self.assertEqual(expected_hash.hexdigest(), hash_all(['jake', 'jones'], digest=hashlib.md5()))

  def test_hash_file(self):
    expected_hash = hashlib.md5()
    expected_hash.update(b'jake jones')

    with temporary_file() as fd:
      fd.write(b'jake jones')
      fd.close()

      self.assertEqual(expected_hash.hexdigest(), hash_file(fd.name, digest=hashlib.md5()))

  def test_compute_shard(self):
    # Spot-check a couple of values, to make sure compute_shard doesn't do something
    # completely degenerate.
    self.assertEqual(31, Sharder.compute_shard('', 42))
    self.assertEqual(35, Sharder.compute_shard('foo', 42))
    self.assertEqual(5, Sharder.compute_shard('bar', 42))

  def test_compute_shard_distribution(self):
    # Check that shard distribution isn't obviously broken.
    nshards = 7
    mean_samples_per_shard = 10000
    nsamples = nshards * mean_samples_per_shard

    distribution = [0] * nshards
    for n in range(0, nsamples):
      shard = Sharder.compute_shard(str(n), nshards)
      distribution[shard] += 1

    variance = sum([(x - mean_samples_per_shard) ** 2 for x in distribution]) / nshards
    stddev = math.sqrt(variance)

    # We arbitrarily assert that a stddev of less than 1% of the mean is good enough
    # for sanity-checking purposes.
    self.assertLess(stddev, 100)

  def test_sharder(self):
    def check(spec, expected_shard, expected_nshards):
      sharder = Sharder(spec)
      self.assertEqual(expected_shard, sharder.shard)
      self.assertEqual(expected_nshards, sharder.nshards)

    def check_bad_spec(spec):
      self.assertRaises(Sharder.InvalidShardSpec, lambda: Sharder(spec))

    check('0/1', 0, 1)
    check('0/2', 0, 2)
    check('1/2', 1, 2)
    check('0/100', 0, 100)
    check('99/100', 99, 100)

    check_bad_spec('0/0')
    check_bad_spec('-1/0')
    check_bad_spec('0/-1')
    check_bad_spec('1/1')
    check_bad_spec('2/1')
    check_bad_spec('100/100')
    check_bad_spec('1/2/3')
    check_bad_spec('/1')
    check_bad_spec('1/')
    check_bad_spec('/')
    check_bad_spec('foo/1')
    check_bad_spec('1/foo')


class CoercingJsonEncodingTest(unittest.TestCase):
  def _coercing_json_encode(self, o, digest=None):
    return json.dumps(o, cls=CoercingEncoder)

  def test_normal_object_encoding(self):
    self.assertEqual(self._coercing_json_encode({}), '{}')
    self.assertEqual(self._coercing_json_encode(()), '[]')
    self.assertEqual(self._coercing_json_encode([]), '[]')
    self.assertEqual(self._coercing_json_encode(set([])), '[]')
    self.assertEqual(self._coercing_json_encode([{}]), '[{}]')
    self.assertEqual(self._coercing_json_encode([('a', 3)]), '[["a", 3]]')
    self.assertEqual(self._coercing_json_encode({'a': 3}), '{"a": 3}')
    self.assertEqual(self._coercing_json_encode([{'a': 3}]), '[{"a": 3}]')
    self.assertEqual(self._coercing_json_encode(set([1])), '[1]')

  def test_rejects_ordered_dict(self):
    with self.assertRaisesRegexp(TypeError, r'CoercingEncoder does not support OrderedDict inputs'):
      self._coercing_json_encode(OrderedDict([('a', 3)]))

  def test_non_string_dict_key_coercion(self):
    self.assertEqual(self._coercing_json_encode({('a', 'b'): 'asdf'}),
                     r'{"[\"a\", \"b\"]": "asdf"}')

  def test_string_like_dict_key_coercion(self):
    self.assertEqual(self._coercing_json_encode({'a': 3}), '{"a": 3}')
    self.assertEqual(self._coercing_json_encode({b'a': 3}), '{"a": 3}')

  def test_nested_dict_key_coercion(self):
    self.assertEqual(self._coercing_json_encode({(1,): {(2,): 3}}),
                     '{"[1]": {"[2]": 3}}')

  def test_collection_ordering(self):
    self.assertEqual(self._coercing_json_encode({2, 1, 3}), '[1, 2, 3]')
    self.assertEqual(self._coercing_json_encode({'b': 4, 'a': 3}), '{"a": 3, "b": 4}')
    self.assertEqual(self._coercing_json_encode([('b', 4), ('a', 3)]), '[["b", 4], ["a", 3]]')
    self.assertEqual(self._coercing_json_encode([{'b': 4, 'a': 3}]),
                     '[{"b": 4, "a": 3}]' if PY3 else '[{"a": 3, "b": 4}]')


class JsonHashingTest(unittest.TestCase):

  def test_known_checksums(self):
    """Check a laundry list of supported inputs to stable_json_sha1().

    This checks both that the method can successfully handle the type of input object, but also that
    the hash of specific objects remains stable.
    """
    self.assertEqual(stable_json_sha1({}), 'bf21a9e8fbc5a3846fb05b4fa0859e0917b2202f')
    self.assertEqual(stable_json_sha1(()), '97d170e1550eee4afc0af065b78cda302a97674c')
    self.assertEqual(stable_json_sha1([]), '97d170e1550eee4afc0af065b78cda302a97674c')
    self.assertEqual(stable_json_sha1(set()), '97d170e1550eee4afc0af065b78cda302a97674c')
    self.assertEqual(stable_json_sha1([{}]), '4e9950a1f2305f56d358cad23f28203fb3aacbef')
    self.assertEqual(stable_json_sha1([('a', 3)]), 'd6abed2e53c1595fb3075ecbe020365a47af1f6f')
    self.assertEqual(stable_json_sha1({'a': 3}), '9e0e6d8a99c72daf40337183358cbef91bba7311')
    self.assertEqual(stable_json_sha1([{'a': 3}]), '8f4e36849a0b8fbe9c4a822c80fbee047c65458a')
    self.assertEqual(stable_json_sha1({1}), 'f629ae44b7b3dcfed444d363e626edf411ec69a8')

  def test_rejects_ordered_dict(self):
    with self.assertRaisesRegexp(TypeError, r'CoercingEncoder does not support OrderedDict inputs'):
      stable_json_sha1(OrderedDict([('a', 3)]))

  def test_non_string_dict_key_checksum(self):
    self.assertEqual(stable_json_sha1({('a', 'b'): 'asdf'}),
                     '45deafcfa78a92522166c77b24f5faaf9f3f5c5a')

  def test_string_like_dict_key_checksum(self):
    self.assertEqual(stable_json_sha1({'a': 3}), '9e0e6d8a99c72daf40337183358cbef91bba7311')
    self.assertEqual(stable_json_sha1({b'a': 3}), '9e0e6d8a99c72daf40337183358cbef91bba7311')

  def test_nested_dict_checksum(self):
    self.assertEqual(stable_json_sha1({(1,): {(2,): 3}}),
                     '63124afed13c4a92eb908fe95c1792528abe3621')

  def test_checksum_ordering(self):
    self.assertEqual(stable_json_sha1(set([2, 1, 3])), 'a01eda32e4e0b1393274e91d1b3e9ecfc5eaba85')
    self.assertEqual(stable_json_sha1({'b': 4, 'a': 3}), '6348df9579e7a72f6ec3fb37751db73b2c97a135')
    self.assertEqual(stable_json_sha1([('b', 4), ('a', 3)]), '8e72bb976e71ea81887eb94730655fe49c454d0c')
    self.assertEqual(stable_json_sha1([{'b': 4, 'a': 3}]), '4735d702f51fb8a98edb9f6f3eb3df1d6d38a77f')
