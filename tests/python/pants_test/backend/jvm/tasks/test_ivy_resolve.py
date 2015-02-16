# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
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

  def resolve(self, targets):
    """Given some targets, execute a resolve, and return the resulting compile_classpath."""
    context = self.context(target_roots=targets)
    self.create_task(context, 'unused').execute()
    return context.products.get_data('compile_classpath', None)

  #
  # Test section
  #

  def test_resolve_specific(self):
    # jar_library with a single dep
    dep = JarDependency('commons-lang', 'commons-lang', '2.5')
    jar_lib = self.make_target('//:a', JarLibrary, jars=[dep])
    scala_lib = self.make_target('//:b', ScalaLibrary)
    # confirm that the deps were added to the appropriate targets
    compile_classpath = self.resolve([jar_lib, scala_lib])
    self.assertEquals(1, len(compile_classpath.get_for_target(jar_lib)))
    self.assertEquals(0, len(compile_classpath.get_for_target(scala_lib)))

  def test_resolve_no_deps(self):
    # resolve for a library with no deps, and confirm that an empty product was created
    target = self.make_target('//:a', ScalaLibrary)
    # confirm that an empty product was created
    assert self.resolve([target])
