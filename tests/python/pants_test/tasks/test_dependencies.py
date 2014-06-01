# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import pytest

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.dependencies import Dependencies
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.exceptions import TaskError

from pants_test.tasks.test_base import ConsoleTaskTest


def jar(org, name, rev):
  return "jar('%s', '%s', '%s')" % (org, name, rev)


class DependenciesEmptyTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return Dependencies

  def test_no_targets(self):
    self.assert_console_output(targets=[])


class NonPythonDependenciesTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return Dependencies

  def setUp(self):
    super(NonPythonDependenciesTest, self).setUp()

    third = self.make_target(
      'dependencies:third',
      target_type=ScalaLibrary,
    )

    first = self.make_target(
      'dependencies:first',
      target_type=ScalaLibrary,
      dependencies=[
        third,
      ],
    )

    second = self.make_target(
      'dependencies:second',
      target_type=JarLibrary,
      jars=[
        JarDependency('org.apache', 'apache-jar', '12.12.2012')
      ],
    )

    project = self.make_target(
      'project:project',
      target_type=ScalaLibrary,
      dependencies=[
        first,
        second,
      ],
    )

  def test_without_dependencies(self):
    self.assert_console_output(
      'dependencies:third',
      targets=[self.target('dependencies:third')]
    )

  def test_all_dependencies(self):
    self.assert_console_output(
      'dependencies:third',
      'dependencies:first',
      'dependencies:second',
      'project:project',
      'org.apache:apache-jar:12.12.2012',
      targets=[self.target('project:project')]
    )

  def test_internal_dependencies(self):
    self.assert_console_output(
      'dependencies:third',
      'dependencies:first',
      'dependencies:second',
      'project:project',
      args=['--test-internal-only'],
      targets=[self.target('project:project')]
    )

  def test_external_dependencies(self):
    self.assert_console_output(
      'org.apache:apache-jar:12.12.2012',
      args=['--test-external-only'],
      targets=[self.target('project:project')]
    )


class PythonDependenciesTests(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return Dependencies

  def setUp(self):
    super(PythonDependenciesTests, self).setUp()

    python_leaf = self.make_target(
      'dependencies:python_leaf',
      target_type=PythonLibrary,
    )

    python_inner = self.make_target(
      'dependencies:python_inner',
      target_type=PythonLibrary,
      dependencies=[
        python_leaf,
      ],
    )

    python_inner_with_external = self.make_target(
      'dependencies:python_inner_with_external',
      target_type=PythonRequirementLibrary,
      requirements=[
        PythonRequirement("antlr_python_runtime==3.1.3")
      ],
    )

    self.make_target(
      'dependencies:python_root',
      target_type=PythonLibrary,
      dependencies=[
        python_inner,
        python_inner_with_external,
      ],
    )

  def test_normal(self):
    self.assert_console_output(
      'antlr-python-runtime==3.1.3',
      'dependencies:python_inner',
      'dependencies:python_inner_with_external',
      'dependencies:python_leaf',
      'dependencies:python_root',
      targets=[self.target('dependencies:python_root')]
    )

  def test_internal_dependencies(self):
    with pytest.raises(TaskError):
      self.assert_console_output(
        args=['--test-internal-only'],
        targets=[self.target('dependencies:python_root')]
      )

  def test_external_dependencies(self):
    with pytest.raises(TaskError):
      self.assert_console_output(
        args=['--test-external-only'],
        targets=[self.target('dependencies:python_root')]
      )
