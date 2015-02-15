# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.ivy_resolve import IvyResolve
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class IvyResolveTest(JvmToolTaskTestBase):
  """Tests for the class IvyResolve."""

  @classmethod
  def task_type(cls):
    return IvyResolve

  def setUp(self):
    super(IvyResolveTest, self).setUp()
    self.set_options(
        read_artifact_caches=None,
        write_artifact_caches=None,
        ng_daemons=False)

  #
  # Test section
  #

  def test_resolve_no_deps(self):
    # resolve for a library with no deps
    target = self.make_target('//:a', ScalaLibrary)
    context = self.context(target_roots=[target])
    self.create_task(context, 'unused').execute()

    # confirm that an empty product was created
    compile_classpath = context.products.get_data('compile_classpath', None)
    assert compile_classpath
