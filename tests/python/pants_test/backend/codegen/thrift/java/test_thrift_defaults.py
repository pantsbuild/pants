# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import uuid
from contextlib import contextmanager

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.thrift.java.thrift_defaults import ThriftDefaults
from pants.build_graph.target import Target
from pants_test.base_test import BaseTest


class TestThriftDefaults(BaseTest):
  def create_thrift_defaults(self, **options):
    self.context(for_subsystems=[ThriftDefaults], options={
      ThriftDefaults.options_scope: options
    })
    return ThriftDefaults.global_instance()

  @contextmanager
  def invalid_fixtures(self):
    target = self.make_target(spec='not_java_thift_library_{}'.format(uuid.uuid4()),
                              target_type=Target)
    thrift_defaults = self.create_thrift_defaults()
    with self.assertRaises(ValueError):
      yield thrift_defaults, target

  def test_compiler_invalid(self):
    with self.invalid_fixtures() as (thrift_defaults, target):
      thrift_defaults.compiler(target)

  def test_language_invalid(self):
    with self.invalid_fixtures() as (thrift_defaults, target):
      thrift_defaults.language(target)

  def test_rpc_style_invalid(self):
    with self.invalid_fixtures() as (thrift_defaults, target):
      thrift_defaults.rpc_style(target)

  def create_thrift_library(self, **kwargs):
    return self.make_target(spec='java_thift_library_{}'.format(uuid.uuid4()),
                            target_type=JavaThriftLibrary,
                            **kwargs)

  def test_compiler(self):
    thrift_defaults = self.create_thrift_defaults(compiler='thrift')
    self.assertEqual('thrift', thrift_defaults.compiler(self.create_thrift_library()))
    self.assertEqual('scrooge',
                     thrift_defaults.compiler(self.create_thrift_library(compiler='scrooge')))

  def test_language(self):
    thrift_defaults = self.create_thrift_defaults(language='java')
    self.assertEqual('java', thrift_defaults.language(self.create_thrift_library()))
    self.assertEqual('scala',
                     thrift_defaults.language(self.create_thrift_library(language='scala')))

  def test_rpc_style(self):
    thrift_defaults = self.create_thrift_defaults(rpc_style='thrift')
    self.assertEqual('thrift', thrift_defaults.rpc_style(self.create_thrift_library()))
    self.assertEqual('finagle',
                     thrift_defaults.rpc_style(self.create_thrift_library(rpc_style='finagle')))
