# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class JvmBinaryTaskTestBase(JvmToolTaskTestBase):

  def create_artifact(self, org, name, rev, classifier=None, ext=None, materialize=True):
    """
    :param string org: The maven dependency `groupId`.
    :param string name: The maven dependency `artifactId`.
    :param string rev: The maven dependency `version`.
    :param string classifier: The maven dependency `classifier`.
    :param string ext: There is no direct maven parallel, but the maven `packaging` value of the
                       depended-on artifact for simple cases, and in more complex cases the
                       extension of the artifact.  For example, 'bundle' packaging implies an
                       extension of 'jar'.  Defaults to 'jar'.
    :param bool materialize: `False` to populate the returned resolved_jar with a `pants_path` that
                             does not exist; defaults to `True` and `touch`es the `pants_path`.
    :returns: A resolved jar describing the artifact.
    :rtype: :class:`pants.backend.jvm.jar_dependency_utils.ResolvedJar`
    """
    coordinate = M2Coordinate(org=org, name=name, rev=rev, classifier=classifier, ext=ext)
    cache_path = 'not/a/real/cache/path'
    jar_name = str(coordinate)
    pants_path = self.create_file(jar_name) if materialize else os.path.join(self.build_root,
                                                                             jar_name)
    return ResolvedJar(coordinate=coordinate, cache_path=cache_path, pants_path=pants_path)

  def iter_files(self, dir_path):
    """Returns an iterator over the files found under the given `dir_path`.

    :param string dir_path: The path of the directory tree to scan for files.
    :returns: An iterator of the relative paths of files found under `dir_path`.
    :rtype: :class:`collections.Iterator` of string
    """
    for root_dir, _, files in os.walk(dir_path):
      for f in files:
        yield os.path.relpath(os.path.join(root_dir, f), dir_path)

  def ensure_classpath_products(self, context):
    """Gets or creates the classpath products expected by `JvmBinaryTask`.

    :param context: The pants run context to get/create/associate classpath products with.
    :type context: :class:`pants.goal.context.Context`
    :returns: The classpath products associated with the given `context`
    :rtype: :class:`pants.backend.jvm.tasks.classpath_products.ClasspathProducts`
    """
    return context.products.get_data('compile_classpath', init_func=ClasspathProducts)
