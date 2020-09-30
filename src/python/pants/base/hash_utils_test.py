# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import json
import re
import unittest
from collections import OrderedDict
from enum import Enum

from pants.base.hash_utils import CoercingEncoder, hash_all, json_hash
from pants.util.ordered_set import OrderedSet


class TestHashUtils(unittest.TestCase):
    def test_hash_all(self):
        expected_hash = hashlib.sha1()
        expected_hash.update(b"jakejones")
        self.assertEqual(expected_hash.hexdigest(), hash_all(["jake", "jones"]))


class CoercingJsonEncodingTest(unittest.TestCase):
    def _coercing_json_encode(self, o):
        return json.dumps(o, cls=CoercingEncoder)

    def test_normal_object_encoding(self):
        self.assertEqual(self._coercing_json_encode({}), "{}")
        self.assertEqual(self._coercing_json_encode(()), "[]")
        self.assertEqual(self._coercing_json_encode([]), "[]")
        self.assertEqual(self._coercing_json_encode(set()), "[]")
        self.assertEqual(self._coercing_json_encode([{}]), "[{}]")
        self.assertEqual(self._coercing_json_encode([("a", 3)]), '[["a", 3]]')
        self.assertEqual(self._coercing_json_encode({"a": 3}), '{"a": 3}')
        self.assertEqual(self._coercing_json_encode([{"a": 3}]), '[{"a": 3}]')
        self.assertEqual(self._coercing_json_encode(set([1])), "[1]")

    def test_rejects_ordered_dict(self):
        with self.assertRaisesRegex(
            TypeError, r"CoercingEncoder does not support OrderedDict inputs"
        ):
            self._coercing_json_encode(OrderedDict([("a", 3)]))

    def test_non_string_dict_key_coercion(self):
        self.assertEqual(
            self._coercing_json_encode({("a", "b"): "asdf"}), r'{"[\"a\", \"b\"]": "asdf"}'
        )

    def test_string_like_dict_key_coercion(self):
        self.assertEqual(self._coercing_json_encode({"a": 3}), '{"a": 3}')
        self.assertEqual(self._coercing_json_encode({b"a": 3}), '{"a": 3}')

    def test_nested_dict_key_coercion(self):
        self.assertEqual(self._coercing_json_encode({(1,): {(2,): 3}}), '{"[1]": {"[2]": 3}}')

    def test_collection_ordering(self):
        self.assertEqual(self._coercing_json_encode({2, 1, 3}), "[1, 2, 3]")
        self.assertEqual(self._coercing_json_encode({"b": 4, "a": 3}), '{"a": 3, "b": 4}')
        self.assertEqual(self._coercing_json_encode([("b", 4), ("a", 3)]), '[["b", 4], ["a", 3]]')
        self.assertEqual(self._coercing_json_encode([{"b": 4, "a": 3}]), '[{"b": 4, "a": 3}]')

    def test_enum(self) -> None:
        class Test(Enum):
            dog = 0
            cat = 1
            pig = 2

        self.assertEqual(self._coercing_json_encode([Test.dog, Test.cat, Test.pig]), "[0, 1, 2]")


class JsonHashingTest(unittest.TestCase):
    def test_known_checksums(self):
        """Check a laundry list of supported inputs to stable_json_sha1().

        This checks both that the method can successfully handle the type of input object, but also
        that the hash of specific objects remains stable.
        """
        self.assertEqual(json_hash({}), "bf21a9e8fbc5a3846fb05b4fa0859e0917b2202f")
        self.assertEqual(json_hash(()), "97d170e1550eee4afc0af065b78cda302a97674c")
        self.assertEqual(json_hash([]), "97d170e1550eee4afc0af065b78cda302a97674c")
        self.assertEqual(json_hash(set()), "97d170e1550eee4afc0af065b78cda302a97674c")
        self.assertEqual(json_hash([{}]), "4e9950a1f2305f56d358cad23f28203fb3aacbef")
        self.assertEqual(json_hash([("a", 3)]), "d6abed2e53c1595fb3075ecbe020365a47af1f6f")
        self.assertEqual(json_hash({"a": 3}), "9e0e6d8a99c72daf40337183358cbef91bba7311")
        self.assertEqual(json_hash([{"a": 3}]), "8f4e36849a0b8fbe9c4a822c80fbee047c65458a")
        self.assertEqual(json_hash({1}), "f629ae44b7b3dcfed444d363e626edf411ec69a8")

    def test_rejects_ordered_collections(self):
        with self.assertRaisesRegex(
            TypeError, re.escape("CoercingEncoder does not support OrderedDict inputs")
        ):
            json_hash(OrderedDict([("a", 3)]))
        with self.assertRaisesRegex(
            TypeError, re.escape("CoercingEncoder does not support OrderedSet inputs")
        ):
            json_hash(OrderedSet([3]))

    def test_non_string_dict_key_checksum(self):
        self.assertEqual(
            json_hash({("a", "b"): "asdf"}), "45deafcfa78a92522166c77b24f5faaf9f3f5c5a"
        )

    def test_string_like_dict_key_checksum(self):
        self.assertEqual(json_hash({"a": 3}), "9e0e6d8a99c72daf40337183358cbef91bba7311")
        self.assertEqual(json_hash({b"a": 3}), "9e0e6d8a99c72daf40337183358cbef91bba7311")

    def test_nested_dict_checksum(self):
        self.assertEqual(json_hash({(1,): {(2,): 3}}), "63124afed13c4a92eb908fe95c1792528abe3621")

    def test_checksum_ordering(self):
        self.assertEqual(json_hash({2, 1, 3}), "a01eda32e4e0b1393274e91d1b3e9ecfc5eaba85")
        self.assertEqual(json_hash({"b": 4, "a": 3}), "6348df9579e7a72f6ec3fb37751db73b2c97a135")
        self.assertEqual(
            json_hash([("b", 4), ("a", 3)]), "8e72bb976e71ea81887eb94730655fe49c454d0c"
        )
        self.assertEqual(json_hash([{"b": 4, "a": 3}]), "4735d702f51fb8a98edb9f6f3eb3df1d6d38a77f")
