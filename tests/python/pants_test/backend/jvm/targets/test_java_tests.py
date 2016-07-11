# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.java_tests import JavaTests
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.target import Target
from pants_test.base_test import BaseTest


class JavaTestsTest(BaseTest):

  def test_validation(self):
    target = self.make_target('//:mybird', Target)
    # A plain invocation with no frills
    test1 = self.make_target('//:test1', JavaTests, sources=["Test.java"], dependencies=[target])
    self.assertIsNone(test1.cwd)
    self.assertIsNone(test1.concurrency)
    self.assertIsNone(test1.threads)
    self.assertIsNone(test1.timeout)

    # cwd parameter
    testcwd = self.make_target('//:testcwd1', JavaTests, sources=["Test.java"],
                               concurrency='SERIAL', cwd='/foo/bar')
    self.assertEquals('/foo/bar', testcwd.cwd)

    # concurrency parameter
    tc1 = self.make_target('//:testconcurrency1', JavaTests, sources=["Test.java"],
                           concurrency='SERIAL')
    self.assertEquals(JavaTests.CONCURRENCY_SERIAL, tc1.concurrency)
    tc2 = self.make_target('//:testconcurrency2', JavaTests, sources=["Test.java"],
                           concurrency='PARALLEL_CLASSES')
    self.assertEquals(JavaTests.CONCURRENCY_PARALLEL_CLASSES, tc2.concurrency)
    tc3 = self.make_target('//:testconcurrency3', JavaTests, sources=["Test.java"],
                           concurrency='PARALLEL_METHODS')
    self.assertEquals(JavaTests.CONCURRENCY_PARALLEL_METHODS, tc3.concurrency)
    tc4 = self.make_target('//:testconcurrency4', JavaTests, sources=["Test.java"],
                           concurrency='PARALLEL_CLASSES_AND_METHODS')
    self.assertEquals(JavaTests.CONCURRENCY_PARALLEL_CLASSES_AND_METHODS, tc4.concurrency)
    with self.assertRaisesRegexp(TargetDefinitionException, r'concurrency'):
      self.make_target('//:testconcurrency5', JavaTests, sources=["Test.java"],
                       concurrency='nonsense')

    # threads parameter
    tt1 = self.make_target('//:testthreads1', JavaTests, sources=["Test.java"], threads=99)
    self.assertEquals(99, tt1.threads)
    tt2 = self.make_target('//:testthreads2', JavaTests, sources=["Test.java"], threads="123")
    self.assertEquals(123, tt2.threads)
    with self.assertRaisesRegexp(TargetDefinitionException, r'threads'):
      self.make_target('//:testthreads3', JavaTests, sources=["Test.java"], threads="abc")

    # timeout parameter
    timeout = self.make_target('//:testtimeout1', JavaTests, sources=["Test.java"], timeout=999)
    self.assertEquals(999, timeout.timeout)
