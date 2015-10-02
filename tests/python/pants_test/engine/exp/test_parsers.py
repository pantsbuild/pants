# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from textwrap import dedent

from pants.engine.exp import parsers
from pants.engine.exp.parsers import ParseError


# A duck-typed Serializable with an `==` suitable for ease of testing.
class Bob(object):
  def __init__(self, **kwargs):
    self._kwargs = kwargs

  def _asdict(self):
    return self._kwargs.copy()

  def _key(self):
    return {k: v for k, v in self._kwargs.items() if k != 'typename'}

  def __eq__(self, other):
    return isinstance(other, Bob) and self._key() == other._key()


class JsonParserTest(unittest.TestCase):
  def test_comments(self):
    document = dedent("""
    # Top level comment.
    {
      # Nested comment
      "hobbies": [1, 2, 3]
    }
    """)
    results = parsers.parse_json(document)
    self.assertEqual(1, len(results))
    self.assertEqual([dict(hobbies=[1, 2, 3])],
                     parsers.parse_json(parsers.encode_json(results[0])))

  def test_single(self):
    document = dedent("""
    # An simple example with a single Bob.
    {
      "typename": "pants_test.engine.exp.test_parsers.Bob",
      "hobbies": [1, 2, 3]
    }
    """)
    results = parsers.parse_json(document)
    self.assertEqual(1, len(results))
    self.assertEqual([Bob(hobbies=[1, 2, 3])],
                     parsers.parse_json(parsers.encode_json(results[0])))
    self.assertEqual('pants_test.engine.exp.test_parsers.Bob', results[0]._asdict()['typename'])

  def test_symbol_table(self):
    symbol_table = {'bob': Bob}
    document = dedent("""
    # An simple example with a single Bob.
    {
      "typename": "bob",
      "hobbies": [1, 2, 3]
    }
    """)
    results = parsers.parse_json(document, symbol_table=symbol_table)
    self.assertEqual(1, len(results))
    self.assertEqual([Bob(hobbies=[1, 2, 3])],
                     parsers.parse_json(parsers.encode_json(results[0]), symbol_table=symbol_table))
    self.assertEqual('bob', results[0]._asdict()['typename'])

  def test_nested_single(self):
    document = dedent("""
    # An example with nested Bobs.
    {
      "typename": "pants_test.engine.exp.test_parsers.Bob",
      "uncle": {
        "typename": "pants_test.engine.exp.test_parsers.Bob",
        "age": 42
      },
      "hobbies": [1, 2, 3]
    }
    """)
    results = parsers.parse_json(document)
    self.assertEqual(1, len(results))
    self.assertEqual([Bob(uncle=Bob(age=42), hobbies=[1, 2, 3])],
                     parsers.parse_json(parsers.encode_json(results[0])))

  def test_nested_deep(self):
    document = dedent("""
    # An example with deeply nested Bobs.
    {
      "typename": "pants_test.engine.exp.test_parsers.Bob",
      "configs": [
        {
          "mappings": {
            "uncle": {
              "typename": "pants_test.engine.exp.test_parsers.Bob",
              "age": 42
            }
          }
        }
      ]
    }
    """)
    results = parsers.parse_json(document)
    self.assertEqual(1, len(results))
    self.assertEqual([Bob(configs=[dict(mappings=dict(uncle=Bob(age=42)))])],
                     parsers.parse_json(parsers.encode_json(results[0])))

  def test_nested_many(self):
    document = dedent("""
    # An example with many nested Bobs.
    {
      "typename": "pants_test.engine.exp.test_parsers.Bob",
      "cousins": [
        {
          "typename": "pants_test.engine.exp.test_parsers.Bob",
          "name": "Jake",
          "age": 42
        },
        {
          "typename": "pants_test.engine.exp.test_parsers.Bob",
          "name": "Jane",
          "age": 37
        }
      ]
    }
    """)
    results = parsers.parse_json(document)
    self.assertEqual(1, len(results))
    self.assertEqual([Bob(cousins=[Bob(name='Jake', age=42), Bob(name='Jane', age=37)])],
                     parsers.parse_json(parsers.encode_json(results[0])))

  def test_multiple(self):
    document = dedent("""
    # An example with several Bobs.

    # One with hobbies.
    {
      "typename": "pants_test.engine.exp.test_parsers.Bob",
      "hobbies": [1, 2, 3]
    }

    # Another that is aged.
    {
      "typename": "pants_test.engine.exp.test_parsers.Bob",
      "age": 42
    }
    """)
    results = parsers.parse_json(document)
    self.assertEqual([Bob(hobbies=[1, 2, 3]), Bob(age=42)], results)

  def test_tricky_spacing(self):
    document = dedent("""
    # An example with several Bobs.

    # One with hobbies.
      {
        "typename": "pants_test.engine.exp.test_parsers.Bob",

        # And internal comment and blank lines.

        "hobbies": [1, 2, 3]} {
      # This comment is inside an empty object that started on the prior line!
    }

    # Another that is aged.
    {"typename": "pants_test.engine.exp.test_parsers.Bob","age": 42}
    """).strip()
    results = parsers.parse_json(document)
    self.assertEqual([Bob(hobbies=[1, 2, 3]), {}, Bob(age=42)], results)

  def test_error_presentation(self):
    document = dedent("""
    # An example with several Bobs.

    # One with hobbies.
      {
        "typename": "pants_test.engine.exp.test_parsers.Bob",

        # And internal comment and blank lines.

        "hobbies": [1, 2, 3]} {
      # This comment is inside an empty object that started on the prior line!
    }

    # Another that is imaginary aged.
    {
      "typename": "pants_test.engine.exp.test_parsers.Bob",
      "age": 42i,

      "four": 1,
      "five": 1,
      "six": 1,
      "seven": 1,
      "eight": 1,
      "nine": 1
    }
    """).strip()
    with self.assertRaises(ParseError) as exc:
      parsers.parse_json(document)

    # Strip trailing whitespace from the message since our expected literal below will have
    # trailing ws stripped via editors and code reviews calling for it.
    actual_lines = [line.rstrip() for line in str(exc.exception).splitlines()]

    # This message from the json stdlib varies between python releases, so fuzz the match a bit.
    self.assertRegexpMatches(actual_lines[0],
                             r"""Expecting (?:,|','|",") delimiter: line 3 column 12 \(char 69\)""")

    self.assertEqual(dedent("""
      In document:
          # An example with several Bobs.

          # One with hobbies.
            {
              "typename": "pants_test.engine.exp.test_parsers.Bob",

              # And internal comment and blank lines.

              "hobbies": [1, 2, 3]} {
            # This comment is inside an empty object that started on the prior line!
          }

          # Another that is imaginary aged.
       1: {
       2:   "typename": "pants_test.engine.exp.test_parsers.Bob",
       3:   "age": 42i,

       4:   "four": 1,
       5:   "five": 1,
       6:   "six": 1,
       7:   "seven": 1,
       8:   "eight": 1,
       9:   "nine": 1
      10: }
      """).strip(), '\n'.join(actual_lines[1:]))


class PythonAssignmentsParserTest(unittest.TestCase):
  def test_no_symbol_table(self):
    document = dedent("""
    from pants_test.engine.exp.test_parsers import Bob

    nancy = Bob(
      hobbies=[1, 2, 3]
    )
    """)
    results = parsers.parse_python_assignments(document)
    self.assertEqual([Bob(name='nancy', hobbies=[1, 2, 3])], results)

    # No symbol table was used so no `typename` plumbing can be expected.
    self.assertNotIn('typename', results[0]._asdict())

  def test_symbol_table(self):
    symbol_table = {'nancy': Bob}
    document = dedent("""
    bill = nancy(
      hobbies=[1, 2, 3]
    )
    """)
    results = parsers.parse_python_assignments(document, symbol_table=symbol_table)
    self.assertEqual([Bob(name='bill', hobbies=[1, 2, 3])], results)
    self.assertEqual('nancy', results[0]._asdict()['typename'])


class PythonCallbacksParserTest(unittest.TestCase):
  def test(self):
    symbol_table = {'nancy': Bob}
    document = dedent("""
    nancy(
      name='bill',
      hobbies=[1, 2, 3]
    )
    """)
    results = parsers.parse_python_callbacks(document, symbol_table)
    self.assertEqual([Bob(name='bill', hobbies=[1, 2, 3])], results)
    self.assertEqual('nancy', results[0]._asdict()['typename'])
