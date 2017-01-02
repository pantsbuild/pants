# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.thrift.java.thrift_defaults import ThriftDefaults
from pants_test.base_test import BaseTest

from pants.contrib.scrooge.tasks.java_thrift_library_fingerprint_strategy import \
  JavaThriftLibraryFingerprintStrategy


class JavaThriftLibraryFingerprintStrategyTest(BaseTest):

  options1 = {'compiler': 'scrooge',
              'language': 'java',
              'rpc_style': 'async'}

  def create_strategy(self, option_values):
    self.context(for_subsystems=[ThriftDefaults], options={
      ThriftDefaults.options_scope: option_values
    })
    return JavaThriftLibraryFingerprintStrategy(ThriftDefaults.global_instance())

  def test_fp_diffs_due_to_option(self):
    option_values = {'compiler': 'scrooge',
                     'language': 'java',
                     'rpc_style': 'finagle'}

    a = self.make_target(':a', target_type=JavaThriftLibrary, dependencies=[])

    fp1 = self.create_strategy(self.options1).compute_fingerprint(a)
    fp2 = self.create_strategy(option_values).compute_fingerprint(a)
    self.assertNotEquals(fp1, fp2)

  def test_fp_diffs_due_to_target_change(self):
    a = self.make_target(':a', target_type=JavaThriftLibrary, rpc_style='sync', dependencies=[])
    b = self.make_target(':b', target_type=JavaThriftLibrary, rpc_style='finagle', dependencies=[])

    fp1 = self.create_strategy(self.options1).compute_fingerprint(a)
    fp2 = self.create_strategy(self.options1).compute_fingerprint(b)
    self.assertNotEquals(fp1, fp2)

  def test_hash_and_equal(self):
    self.assertEqual(self.create_strategy(self.options1), self.create_strategy(self.options1))
    self.assertEqual(hash(self.create_strategy(self.options1)),
                     hash(self.create_strategy(self.options1)))

    option_values = {'compiler': 'scrooge',
                     'language': 'java',
                     'rpc_style': 'finagle'}
    self.assertNotEqual(self.create_strategy(self.options1), self.create_strategy(option_values))
    self.assertNotEqual(hash(self.create_strategy(self.options1)),
                        hash(self.create_strategy(option_values)))
