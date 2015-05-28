# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants_test.base.context_utils import create_options
from pants_test.base_test import BaseTest

from pants.contrib.scrooge.tasks.java_thrift_library_fingerprint_strategy import \
  JavaThriftLibraryFingerprintStrategy


class JavaThriftLibraryFingerprintStrategyTest(BaseTest):

  option_values = {'thrift_default_compiler': 'scrooge',
                    'thrift_default_language': 'java',
                    'thrift_default_rpc_style': 'async'}
  options1 = create_options({'': option_values})

  def test_fp_diffs_due_to_option(self):
    option_values = {'thrift_default_compiler': 'scrooge',
                     'thrift_default_language': 'java',
                     'thrift_default_rpc_style': 'finagle'}
    options2 = create_options({'': option_values})

    a = self.make_target(':a', target_type=JavaThriftLibrary, dependencies=[])

    fp1 = JavaThriftLibraryFingerprintStrategy(self.options1).compute_fingerprint(a)
    fp2 = JavaThriftLibraryFingerprintStrategy(options2).compute_fingerprint(a)
    self.assertNotEquals(fp1, fp2)

  def test_fp_diffs_due_to_target_change(self):
    a = self.make_target(':a', target_type=JavaThriftLibrary,
                         rpc_style='sync', dependencies=[])
    b = self.make_target(':b', target_type=JavaThriftLibrary,
                         rpc_style='finagle', dependencies=[])

    fp1 = JavaThriftLibraryFingerprintStrategy(self.options1).compute_fingerprint(a)
    fp2 = JavaThriftLibraryFingerprintStrategy(self.options1).compute_fingerprint(b)
    self.assertNotEquals(fp1, fp2)

  def test_hash_and_equal(self):
    self.assertEqual(
      JavaThriftLibraryFingerprintStrategy(None),
      JavaThriftLibraryFingerprintStrategy(None),
    )
    self.assertEqual(
      JavaThriftLibraryFingerprintStrategy(self.options1),
      JavaThriftLibraryFingerprintStrategy(self.options1),
    )
    self.assertEqual(
      hash(JavaThriftLibraryFingerprintStrategy(self.options1)),
      hash(JavaThriftLibraryFingerprintStrategy(self.options1)),
    )
    option_values = {'thrift_default_compiler': 'scrooge',
                     'thrift_default_language': 'java',
                     'thrift_default_rpc_style': 'finagle'}
    options2 = create_options({'': option_values})
    self.assertNotEqual(
      hash(JavaThriftLibraryFingerprintStrategy(self.options1)),
      hash(JavaThriftLibraryFingerprintStrategy(options2)),
    )
