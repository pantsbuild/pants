# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

import pytest

from pants.tasks.dependencies import Dependencies
from pants.tasks.task_error import TaskError
from pants.tasks.test_base import ConsoleTaskTest


# some helper methods to be able to setup the state in a cleaner way
def pants(path):
  return "pants('%s')" % path

def jar(org, name, rev):
  return "jar('%s', '%s', '%s')" % (org, name, rev)

def python_requirement(name):
  return "python_requirement('%s')" % name


class BaseDependenciesTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return Dependencies

  @classmethod
  def define_target(cls, path, name, ttype='python_library', deps=()):
    cls.create_target(path, dedent('''
        %(type)s(name='%(name)s',
          dependencies=[%(deps)s]
        )
        ''' % dict(
      type=ttype,
      name=name,
      deps=','.join(deps))
    ))

  @classmethod
  def scala_library(cls, path, name, deps=()):
    cls.create_target(path, dedent('''
      scala_library(name='%(name)s',
        dependencies=[%(deps)s],
        sources=[],
      )
    ''' % dict(
      name=name,
      deps=','.join(deps))
    ))


class DependenciesEmptyTest(BaseDependenciesTest):
  def test_no_targets(self):
    self.assert_console_output(targets=[])

class NonPythonDependenciesTest(BaseDependenciesTest):
  @classmethod
  def setUpClass(cls):
    super(NonPythonDependenciesTest, cls).setUpClass()

    cls.scala_library('dependencies', 'third')
    cls.scala_library('dependencies', 'first',
      deps=[pants('dependencies:third')])

    cls.scala_library('dependencies', 'second',
      deps=[
        jar('org.apache', 'apache-jar', '12.12.2012')]);

    cls.scala_library('project', 'project',
      deps=[
        pants('dependencies:first'),
        pants('dependencies:second')])

  def test_without_dependencies(self):
    self.assert_console_output(
      'dependencies/BUILD:third',
      targets=[self.target('dependencies:third')]
    )

  def test_all_dependencies(self):
    self.assert_console_output(
      'dependencies/BUILD:third',
      'dependencies/BUILD:first',
      'dependencies/BUILD:second',
      'project/BUILD:project',
      'org.apache:apache-jar:12.12.2012',
      targets=[self.target('project:project')]
    )

  def test_internal_dependencies(self):
    self.assert_console_output(
      'dependencies/BUILD:third',
      'dependencies/BUILD:first',
      'dependencies/BUILD:second',
      'project/BUILD:project',
      args=['--test-internal-only'],
      targets=[self.target('project:project')]
    )

  def test_external_dependencies(self):
    self.assert_console_output(
      'org.apache:apache-jar:12.12.2012',
      args=['--test-external-only'],
      targets=[self.target('project:project')]
    )


class PythonDependenciesTests(BaseDependenciesTest):
  @classmethod
  def setUpClass(cls):
    super(PythonDependenciesTests, cls).setUpClass()

    cls.define_target('dependencies', 'python_leaf')

    cls.define_target('dependencies', 'python_inner',
      deps=[
        pants('dependencies:python_leaf')
      ])

    cls.define_target('dependencies', 'python_inner_with_external',
      deps=[
        python_requirement("antlr_python_runtime==3.1.3")
      ])

    cls.define_target('dependencies', 'python_root',
      deps=[
        pants('dependencies:python_inner'),
        pants('dependencies:python_inner_with_external')
      ])

  def test_normal(self):
    self.assert_console_output(
      'antlr-python-runtime==3.1.3',
      'dependencies/BUILD:python_inner',
      'dependencies/BUILD:python_inner_with_external',
      'dependencies/BUILD:python_leaf',
      'dependencies/BUILD:python_root',
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
