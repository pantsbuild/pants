# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.util.dirutil import safe_file_dump, safe_mkdir, safe_mkdtemp
from pants_test.tasks.task_test_base import TaskTestBase


class JvmTaskTestBase(TaskTestBase):
  """
  :API: public
  """

  def populate_runtime_classpath(self, context, classpath=None):
    """
    Helps actual test cases to populate the 'runtime_classpath' products data mapping
    in the context, which holds the classpath value for targets.

    :API: public

    :param context: The execution context where the products data mapping lives.
    :param classpath: a list of classpath strings. If not specified,
                      [os.path.join(self.buildroot, 'none')] will be used.
    """
    classpath = classpath or []
    runtime_classpath = self.get_runtime_classpath(context)
    runtime_classpath.add_for_targets(context.targets(),
                                      [('default', entry) for entry in classpath])

  def add_to_runtime_classpath(self, context, tgt, files_dict):
    """Creates and adds the given files to the classpath for the given target under a temp path.

    :API: public
    """
    runtime_classpath = self.get_runtime_classpath(context)
    # Create a temporary directory under the target id, then dump all files.
    target_dir = os.path.join(self.test_workdir, tgt.id)
    safe_mkdir(target_dir)
    classpath_dir = safe_mkdtemp(dir=target_dir)
    for rel_path, content in files_dict.items():
      safe_file_dump(os.path.join(classpath_dir, rel_path), content)
    # Add to the classpath.
    runtime_classpath.add_for_target(tgt, [('default', classpath_dir)])

  def get_runtime_classpath(self, context):
    """
    :API: public
    """
    return context.products.get_data('runtime_classpath', init_func=ClasspathProducts.init_func(self.pants_workdir))
