# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.setup_py import NativeToolchainEnvironment
from pants.task.task import Task
from pants.util.memo import memoized_property

from pants.contrib.native.subsystems.native_toolchain import NativeToolchain


class PopulateNativeEnvironment(Task):

  @classmethod
  def product_types(cls):
    return [NativeToolchainEnvironment]

  @classmethod
  def subsystem_dependencies(cls):
    return super(PopulateNativeEnvironment, cls).subsystem_dependencies() + (
      NativeToolchain.scoped(cls),
    )

  @memoized_property
  def _native_toolchain(self):
    return NativeToolchain.scoped_instance(self)

  def _request_single(self, product, subject):
    # This is not supposed to be exposed to Tasks yet -- see #4769 to track the
    # status of exposing v2 products in v1 tasks.
    return self.context._scheduler.product_request(product, [subject])[0]

  def execute(self):
    env = self._request_single(NativeToolchainEnvironment, self._native_toolchain)
    self.context.products.register_data(NativeToolchainEnvironment, env)
