# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import unittest
from builtins import object, str
from textwrap import dedent

from pants.engine import parser
from pants.engine.objects import Resolvable
from pants_test.engine.examples import parsers
from pants_test.testutils.py2_compat import assertRegex


# A duck-typed Serializable with an `==` suitable for ease of testing.
class Bob(object):
  def __init__(self, **kwargs):
    self._kwargs = kwargs

  def _asdict(self):
    return self._kwargs

  def _key(self):
    return {k: v for k, v in self._kwargs.items() if k != 'type_alias'}

  def __eq__(self, other):
    return isinstance(other, Bob) and self._key() == other._key()


EMPTY_TABLE = parser.SymbolTable({})


TEST_TABLE = parser.SymbolTable({'bob': Bob})


TEST_TABLE2 = parser.SymbolTable({'nancy': Bob})


def parse(parser, document, **args):
  return parser.parse('/dev/null', document, **args)


class JsonParserTest(unittest.TestCase):
  def parse(self, document, symbol_table=None, **kwargs):
    symbol_table = symbol_table or EMPTY_TABLE
    return parse(parsers.JsonParser(symbol_table), document, **kwargs)

  def round_trip(self, obj, symbol_table=None):
    document = parsers.encode_json(obj, inline=True)
    return self.parse(document, symbol_table=symbol_table)

  def test_comments(self):
    document = dedent("""
    # Top level comment.
    {
      # Nested comment
      "hobbies": [1, 2, 3]
    }
    """)
    results = self.parse(document)
    self.assertEqual(1, len(results))
    self.assertEqual([dict(hobbies=[1, 2, 3])], self.round_trip(results[0]))

  def test_single(self):
    document = dedent("""
    # A simple example with a single Bob.
    {
      "type_alias": "pants_test.engine.test_parsers.Bob",
      "hobbies": [1, 2, 3]
    }
    """)
    results = self.parse(document)
    self.assertEqual(1, len(results))
    self.assertEqual([Bob(hobbies=[1, 2, 3])], self.round_trip(results[0]))
    self.assertEqual('pants_test.engine.test_parsers.Bob', results[0]._asdict()['type_alias'])

  def test_symbol_table(self):
    document = dedent("""
    # An simple example with a single Bob.
    {
      "type_alias": "bob",
      "hobbies": [1, 2, 3]
    }
    """)
    results = self.parse(document, symbol_table=TEST_TABLE)
    self.assertEqual(1, len(results))
    self.assertEqual([Bob(hobbies=[1, 2, 3])],
                     self.round_trip(results[0], symbol_table=TEST_TABLE))
    self.assertEqual('bob', results[0]._asdict()['type_alias'])

  def test_nested_single(self):
    document = dedent("""
    # An example with nested Bobs.
    {
      "type_alias": "pants_test.engine.test_parsers.Bob",
      "uncle": {
        "type_alias": "pants_test.engine.test_parsers.Bob",
        "age": 42
      },
      "hobbies": [1, 2, 3]
    }
    """)
    results = self.parse(document)
    self.assertEqual(1, len(results))
    self.assertEqual([Bob(uncle=Bob(age=42), hobbies=[1, 2, 3])], self.round_trip(results[0]))

  def test_nested_deep(self):
    document = dedent("""
    # An example with deeply nested Bobs.
    {
      "type_alias": "pants_test.engine.test_parsers.Bob",
      "configs": [
        {
          "mappings": {
            "uncle": {
              "type_alias": "pants_test.engine.test_parsers.Bob",
              "age": 42
            }
          }
        }
      ]
    }
    """)
    results = self.parse(document)
    self.assertEqual(1, len(results))
    self.assertEqual([Bob(configs=[dict(mappings=dict(uncle=Bob(age=42)))])],
                     self.round_trip(results[0]))

  def test_nested_many(self):
    document = dedent("""
    # An example with many nested Bobs.
    {
      "type_alias": "pants_test.engine.test_parsers.Bob",
      "cousins": [
        {
          "type_alias": "pants_test.engine.test_parsers.Bob",
          "name": "Jake",
          "age": 42
        },
        {
          "type_alias": "pants_test.engine.test_parsers.Bob",
          "name": "Jane",
          "age": 37
        }
      ]
    }
    """)
    results = self.parse(document)
    self.assertEqual(1, len(results))
    self.assertEqual([Bob(cousins=[Bob(name='Jake', age=42), Bob(name='Jane', age=37)])],
                     self.round_trip(results[0]))

  def test_multiple(self):
    document = dedent("""
    # An example with several Bobs.

    # One with hobbies.
    {
      "type_alias": "pants_test.engine.test_parsers.Bob",
      "hobbies": [1, 2, 3]
    }

    # Another that is aged.
    {
      "type_alias": "pants_test.engine.test_parsers.Bob",
      "age": 42
    }
    """)
    results = self.parse(document)
    self.assertEqual([Bob(hobbies=[1, 2, 3]), Bob(age=42)], results)

  def test_tricky_spacing(self):
    document = dedent("""
    # An example with several Bobs.

    # One with hobbies.
      {
        "type_alias": "pants_test.engine.test_parsers.Bob",

        # And internal comment and blank lines.

        "hobbies": [1, 2, 3]} {
      # This comment is inside an empty object that started on the prior line!
    }

    # Another that is aged.
    {"type_alias": "pants_test.engine.test_parsers.Bob","age": 42}
    """).strip()
    results = self.parse(document)
    self.assertEqual([Bob(hobbies=[1, 2, 3]), {}, Bob(age=42)], results)

  def test_error_presentation(self):
    document = dedent("""
    # An example with several Bobs.

    # One with hobbies.
      {
        "type_alias": "pants_test.engine.test_parsers.Bob",

        # And internal comment and blank lines.

        "hobbies": [1, 2, 3]} {
      # This comment is inside an empty object that started on the prior line!
    }

    # Another that is imaginary aged.
    {
      "type_alias": "pants_test.engine.test_parsers.Bob",
      "age": 42i,

      "four": 1,
      "five": 1,
      "six": 1,
      "seven": 1,
      "eight": 1,
      "nine": 1
    }
    """).strip()
    filepath = '/dev/null'
    with self.assertRaises(parser.ParseError) as exc:
      parsers.JsonParser(EMPTY_TABLE).parse(filepath, document)

    # Strip trailing whitespace from the message since our expected literal below will have
    # trailing ws stripped via editors and code reviews calling for it.
    actual_lines = [line.rstrip() for line in str(exc.exception).splitlines()]

    # This message from the json stdlib varies between python releases, so fuzz the match a bit.
    assertRegex(self, actual_lines[0],
                             r'Expecting (?:,|\',\'|",") delimiter: line 3 column 12 \(char 67\)')

    self.assertEqual(dedent("""
      In document at {filepath}:
          # An example with several Bobs.

          # One with hobbies.
            {{
              "type_alias": "pants_test.engine.test_parsers.Bob",

              # And internal comment and blank lines.

              "hobbies": [1, 2, 3]}} {{
            # This comment is inside an empty object that started on the prior line!
          }}

          # Another that is imaginary aged.
       1: {{
       2:   "type_alias": "pants_test.engine.test_parsers.Bob",
       3:   "age": 42i,

       4:   "four": 1,
       5:   "five": 1,
       6:   "six": 1,
       7:   "seven": 1,
       8:   "eight": 1,
       9:   "nine": 1
      10: }}
      """.format(filepath=filepath)).strip(), '\n'.join(actual_lines[1:]))


class JsonEncoderTest(unittest.TestCase):

  def setUp(self):
    bill = Bob(name='bill')

    class SimpleResolvable(Resolvable):
      @property
      def address(self):
        return '::an opaque address::'

      def resolve(self):
        return bill

    resolvable_bill = SimpleResolvable()

    self.bob = Bob(name='bob', relative=resolvable_bill, friend=bill)

  def test_shallow_encoding(self):
    expected_json = dedent("""
    {
      "name": "bob",
      "type_alias": "pants_test.engine.test_parsers.Bob",
      "friend": {
        "name": "bill",
        "type_alias": "pants_test.engine.test_parsers.Bob"
      },
      "relative": "::an opaque address::"
    }
    """).strip()
    self.assertEqual(json.dumps(json.loads(expected_json), sort_keys=True),
                     parsers.encode_json(self.bob, inline=False, sort_keys=True))

  def test_inlined_encoding(self):
    expected_json = dedent("""
    {
      "name": "bob",
      "type_alias": "pants_test.engine.test_parsers.Bob",
      "friend": {
        "name": "bill",
        "type_alias": "pants_test.engine.test_parsers.Bob"
      },
      "relative": {
        "name": "bill",
        "type_alias": "pants_test.engine.test_parsers.Bob"
      }
    }
    """).strip()
    self.assertEqual(json.dumps(json.loads(expected_json), sort_keys=True),
                     parsers.encode_json(self.bob, inline=True, sort_keys=True))


class PythonAssignmentsParserTest(unittest.TestCase):
  def test_no_symbol_table(self):
    document = dedent("""
    from pants_test.engine.test_parsers import Bob

    nancy = Bob(
      hobbies=[1, 2, 3]
    )
    """)
    results = parse(parsers.PythonAssignmentsParser(EMPTY_TABLE), document)
    self.assertEqual([Bob(name='nancy', hobbies=[1, 2, 3])], results)

    # No symbol table was used so no `type_alias` plumbing can be expected.
    self.assertNotIn('type_alias', results[0]._asdict())

  def test_symbol_table(self):
    document = dedent("""
    bill = nancy(
      hobbies=[1, 2, 3]
    )
    """)
    results = parse(parsers.PythonAssignmentsParser(TEST_TABLE2), document)
    self.assertEqual([Bob(name='bill', hobbies=[1, 2, 3])], results)
    self.assertEqual('nancy', results[0]._asdict()['type_alias'])


class PythonCallbacksParserTest(unittest.TestCase):
  def test(self):
    document = dedent("""
    nancy(
      name='bill',
      hobbies=[1, 2, 3]
    )
    """)
    results = parse(parsers.PythonCallbacksParser(TEST_TABLE2), document)
    self.assertEqual([Bob(name='bill', hobbies=[1, 2, 3])], results)
    self.assertEqual('nancy', results[0]._asdict()['type_alias'])
