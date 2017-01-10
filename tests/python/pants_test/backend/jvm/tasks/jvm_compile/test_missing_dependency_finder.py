# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import random
import unittest

from pants.backend.jvm.tasks.jvm_compile.class_not_found_error_patterns import \
  CLASS_NOT_FOUND_ERROR_PATTERNS
from pants.backend.jvm.tasks.jvm_compile.missing_dependency_finder import (ClassNotFoundError,
                                                                           CompileErrorExtractor,
                                                                           StringSimilarityRanker)


class CompileErrorExtractorTest(unittest.TestCase):
  ERROR_MESSAGES = [
    r"""
      [error] /path/to/file/Hello.java:3:1: cannot find symbol
      [error]   symbol:   class Nullable
      [error]   location: package javax.annotation
      [error] import javax.annotation.Nullable;""",
    r"""
      [error] /path/to/file/Hello.java:63:1: cannot access org.apache.thrift.TBase
      [error]   class file for org.apache.thrift.TBase not found""",
    r"""
      [error] /path/to/file/Hello.java:6:1: package a.b.c does not exist
      [error] import a.b.c.ImmutableMap;""",
    r"""
      [error] /path/to/file/Hello.java:36:1: cannot find symbol
      [error]   symbol:   class XYZ
      [error]   location: package a.b.c""",
    r"""
      [error] /path/to/file/Hello.java:102:1: package a.b.c does not exist
      [error]     public static final A<a.b.c.XYZ> xyz = new ...;    """,
    r"""
      [error] ## Exception when compiling /path/to/file/Hello.java and others...
      [error] Type com.twitter.util.lint.Rule not present""",
    r"""
      [error] ## Exception when compiling /path/to/file/Hello.java and others...
      [error] java.lang.NoClassDefFoundError: a.b.c.XYZ""",
    r"""
      [error] /path/to/file/Hello.scala:211:26: exception during macro expansion:
      [error] java.lang.ClassNotFoundException: com.twitter.x.thrift.thriftscala.Y""",
    r"""
      [error] /path/to/file/Hello.scala:7:33: object x is not a member of package a.b.c
      [error] import a.b.c.x.Y""",
    r"""
      java.lang.NoClassDefFoundError: org/apache/thrift/TEnum""",
    r"""
      [error] missing or invalid dependency detected while loading class file 'Logging.class'.
      [error] Could not access type Future in value com.twitter.util,""",
    r"""
      [error] Class a.b.c.X not found - continuing with a stub.""",
  ]

  EXPECTED_ERRORS = [
    ClassNotFoundError('/path/to/file/Hello.java', '3', 'javax.annotation.Nullable'),
    ClassNotFoundError('/path/to/file/Hello.java', '63', 'org.apache.thrift.TBase'),
    ClassNotFoundError('/path/to/file/Hello.java', '6', 'a.b.c.ImmutableMap'),
    ClassNotFoundError('/path/to/file/Hello.java', '36', 'a.b.c.XYZ'),
    ClassNotFoundError('/path/to/file/Hello.java', '102', 'a.b.c.XYZ'),
    ClassNotFoundError('/path/to/file/Hello.java', None, 'com.twitter.util.lint.Rule'),
    ClassNotFoundError('/path/to/file/Hello.java', None, 'a.b.c.XYZ'),
    ClassNotFoundError('/path/to/file/Hello.scala', '211', 'com.twitter.x.thrift.thriftscala.Y'),
    ClassNotFoundError('/path/to/file/Hello.scala', '7', 'a.b.c.x.Y'),
    ClassNotFoundError(None, None, 'org.apache.thrift.TEnum'),
    ClassNotFoundError(None, None, 'com.twitter.util.Future'),
    ClassNotFoundError(None, None, 'a.b.c.X'),
  ]

  def setUp(self):
    self.compile_error_finder = CompileErrorExtractor(CLASS_NOT_FOUND_ERROR_PATTERNS)

  def test_extract_single_error(self):
    for error_message, expected_error in zip(self.ERROR_MESSAGES, self.EXPECTED_ERRORS):
      self.assertEqual([expected_error], self.compile_error_finder.extract(error_message))

  def test_extract_all_errors(self):
    compile_log = '\n'.join(self.ERROR_MESSAGES)
    self.assertEqual(self.EXPECTED_ERRORS,
      self.compile_error_finder.extract(compile_log))


class StringSimilarityRankerTest(unittest.TestCase):
  def test_rank_dependency_candidates(self):
    not_found_classname = 'com.google.inject.Inject'

    # Expect 3rdparty/jvm/com/google/inject:guice is more similar to the missing class name.
    expected = [
      '3rdparty/jvm/com/google/inject:guice',
      '3rdparty/jvm/com/google/guava:guava',
      '3rdparty/jvm/cascading:cascading-local',
    ]

    shuffled = list(expected)
    random.shuffle(shuffled)
    self.assertEqual(expected, StringSimilarityRanker(not_found_classname).sort(shuffled))
