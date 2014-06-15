# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants_test.jvm.jar_task_test_base import JarTaskTestBase


class JvmBinaryTestBase(JarTaskTestBase):
  """Prepares an ephemeral test build root that supports jvm binary tasks."""

  def create_options(self, **kwargs):
    options = dict(jvm_binary_create_outdir=None,
                   jvm_binary_create_deployjar=False)
    options.update(**kwargs)
    return super(JvmBinaryTestBase, self).create_options(**options)
