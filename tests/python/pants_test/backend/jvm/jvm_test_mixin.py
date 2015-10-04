# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.classpath_products import ClasspathProducts


class JvmTestMixin(object):
  """A test mixin providing JVM product population helpers."""

  def populate_classpath(self, context, classpath=None, product_name='compile_classpath'):
    """
    Helps actual test cases to populate the 'compile_classpath' products data mapping
    in the context, which holds the classpath value for targets.

    :param context: The execution context where the products data mapping lives.
    :param classpath: a list of classpath entries. If not specified, [] will be used.
    :param product_name: The name of the classpath product to populate, or 'compile_classpath'.
    """
    classpath = classpath or []
    compile_classpaths = context.products.get_data(product_name, lambda: ClasspathProducts())
    compile_classpaths.add_for_targets(context.targets(),
                                       [('default', entry) for entry in classpath])
