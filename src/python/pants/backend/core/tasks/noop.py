# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.task import Task


class NoopExecTask(Task):
  """A base class for tasks which do nothing but produce some product_type(s).

    Useful when scheduling a specific goal, as one can install subclasses of this which produce a
    known product_type into that goal, then depend on those products elsewhere.

    Generally tasks depend on a specific product or products, as opposed to a given goal, and do
    not need this, but some tasks, eg "compile changed targets" just know they want the "compile"
    goal to be run, rather than a specific product, eg jvm classfiles.
  """

  def execute(self):
    pass


class NoopCompile(NoopExecTask):
  """A no-op that provides a product type that can be used to force scheduling."""

  @classmethod
  def product_types(cls):
    return ['ran_compile']


class NoopTest(NoopExecTask):
  """A no-op that provides a product type that can be used to force scheduling."""

  @classmethod
  def product_types(cls):
    return ['ran_tests']
