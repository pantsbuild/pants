# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
from builtins import open

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import Exiter
from pants.task.task import Task
from pants.util.memo import memoized_property

from pants.contrib.scrooge.tasks.scrooge_gen import ScroogeGen


class ThriftPreprocessStub(ScroogeGen):

  @classmethod
  def product_types(cls):
    return ['thrift-preprocess']

  def is_gentarget(self, target):
    return isinstance(target, JavaThriftLibrary)

  def execute_codegen(self, target, target_workdir):
    preprocessed_thrift_product = self.context.products.get('thrift-preprocess')
    preprocessed_thrift_product.add(target, target.address.spec_path)
