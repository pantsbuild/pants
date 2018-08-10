# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.project_info.tasks.dependencies import Dependencies
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.build_graph.target import Target
from pants.java.jar.jar_dependency import JarDependency
from pants_test.task_test_base import ConsoleTaskTestBase


class DependenciesEmptyTest(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return Dependencies

  def test_no_targets(self):
    self.assert_console_output(targets=[])


class NonPythonDependenciesTest(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return Dependencies

  def setUp(self):
    super(NonPythonDependenciesTest, self).setUp()

    third = self.make_target(
      'dependencies:third',
      target_type=JavaLibrary,
      sources=[],
    )

    first = self.make_target(
      'dependencies:first',
      target_type=JavaLibrary,
      sources=[],
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
      target_type=JavaLibrary,
      sources=[],
      dependencies=[
        first,
        second,
      ],
    )

    self.make_target(
      'project:dep-bag',
      target_type=Target,
      dependencies=[
        second,
        project
      ]
    )

  def test_without_dependencies(self):
    self.assert_console_output_ordered(
      'dependencies:third',
      targets=[self.target('dependencies:third')]
    )

  def test_all_dependencies(self):
    self.assert_console_output_ordered(
      'project:project',
      'dependencies:first',
      'dependencies:third',
      'dependencies:second',
      'org.apache:apache-jar:12.12.2012',
      targets=[self.target('project:project')]
    )

  def test_internal_dependencies(self):
    self.assert_console_output_ordered(
      'project:project',
      'dependencies:first',
      'dependencies:third',
      'dependencies:second',
      targets=[self.target('project:project')],
      options={'internal_only': True}
    )

  def test_external_dependencies(self):
    self.assert_console_output_ordered(
      'org.apache:apache-jar:12.12.2012',
      targets=[self.target('project:project')],
      options={'external_only': True}
    )

  def test_dep_bag(self):
    self.assert_console_output_ordered(
      'project:dep-bag',
      'dependencies:second',
      'org.apache:apache-jar:12.12.2012',
      'project:project',
      'dependencies:first',
      'dependencies:third',
      targets=[self.target('project:dep-bag')]
    )

  def test_intransitive_internal_dependencies(self):
    self.assert_console_output_ordered(
      'dependencies:first',
      'dependencies:second',
      targets=[self.target('project:project')],
      options={'transitive': False, 'internal_only': True}
    )

  def test_intransitive_external_dependencies(self):
    self.assert_console_output_ordered(
      'org.apache:apache-jar:12.12.2012',
      targets=[self.target('project:project')],
      options={'transitive': False, 'external_only': True}
    )


class PythonDependenciesTests(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return Dependencies

  def setUp(self):
    super(PythonDependenciesTests, self).setUp()

    python_leaf = self.make_target(
      'dependencies:python_leaf',
      target_type=PythonLibrary,
      sources=[],
    )

    python_inner = self.make_target(
      'dependencies:python_inner',
      target_type=PythonLibrary,
      sources=[],
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
      sources=[],
      dependencies=[
        python_inner,
        python_inner_with_external,
      ],
    )

  def test_normal(self):
    self.assert_console_output_ordered(
      'dependencies:python_root',
      'dependencies:python_inner',
      'dependencies:python_leaf',
      'dependencies:python_inner_with_external',
      'antlr_python_runtime==3.1.3',
      targets=[self.target('dependencies:python_root')]
    )

  def test_internal_dependencies(self):
    self.assert_console_output_ordered(
      'dependencies:python_root',
      'dependencies:python_inner',
      'dependencies:python_leaf',
      'dependencies:python_inner_with_external',
      targets=[self.target('dependencies:python_root')],
      options={'internal_only': True}
    )

  def test_external_dependencies(self):
    self.assert_console_output_ordered(
      'antlr_python_runtime==3.1.3',
      targets=[self.target('dependencies:python_root')],
      options={'external_only': True}
    )

  def test_intransitive_internal_dependencies(self):
    self.assert_console_output_ordered(
      'dependencies:python_inner',
      'dependencies:python_inner_with_external',
      targets=[self.target('dependencies:python_root')],
      options={'transitive': False, 'internal_only': True}
    )

  def test_intransitive_external_dependencies(self):
    self.assert_console_output_ordered(
      'antlr_python_runtime==3.1.3',
      targets=[self.target('dependencies:python_root')],
      options={'transitive': False, 'external_only': True}
    )
