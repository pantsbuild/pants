# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

import mox

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.targets.resources import Resources
from pants.backend.core.tasks.dependees import ReverseDepmap
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot

from pants_test.tasks.test_base import ConsoleTaskTest


class BaseReverseDepmapTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return ReverseDepmap


class ReverseDepmapEmptyTest(BaseReverseDepmapTest):
  def test(self):
    self.assert_console_output(targets=[])


class ReverseDepmapTest(mox.MoxTestBase, BaseReverseDepmapTest):
  @property
  def alias_groups(self):
    return {
      'target_aliases': {
        'dependencies': Dependencies,
        'jar_library': JarLibrary,
        'java_library': JavaLibrary,
        'java_thrift_library': JavaThriftLibrary,
        'python_library': PythonLibrary,
        'python_tests': PythonTests,
        'resources': Resources,
        'scala_library': ScalaLibrary,
      },
      'exposed_objects': {
        'jar': JarDependency,
      },
    }

  def setUp(self):
    super(ReverseDepmapTest, self).setUp()

    def add_to_build_file(path, name, alias=False, deps=()):
      self.add_to_build_file(path, dedent('''
          %(type)s(name='%(name)s',
            dependencies=[%(deps)s]
          )
          ''' % dict(
        type='dependencies' if alias else 'python_library',
        name=name,
        deps=','.join("'%s'" % dep for dep in list(deps)))
      ))

    add_to_build_file('common/a', 'a', deps=['common/d'])
    add_to_build_file('common/b', 'b')
    add_to_build_file('common/c', 'c')
    add_to_build_file('common/d', 'd')
    add_to_build_file('tests/d', 'd', deps=['common/d'])
    add_to_build_file('overlaps', 'one', deps=['common/a', 'common/b'])
    add_to_build_file('overlaps', 'two', deps=['common/a', 'common/c'])
    add_to_build_file('overlaps', 'three', deps=['common/a', 'overlaps:one'])
    add_to_build_file('overlaps', 'four', alias=True, deps=['common/b'])
    add_to_build_file('overlaps', 'five', deps=['overlaps:four'])

    self.add_to_build_file('resources/a', dedent('''
      resources(
        name='a_resources',
        sources=['a.resource']
      )
    '''))

    self.add_to_build_file('src/java/a', dedent('''
      java_library(
        name='a_java',
        resources=['resources/a:a_resources']
      )
    '''))

    #Compile idl tests
    self.add_to_build_file('src/thrift/example', dedent('''
      java_thrift_library(
        name='mybird',
        compiler='scrooge',
        language='scala',
        sources=['1.thrift']
      )
      '''))

    self.add_to_build_file('src/thrift/example', dedent('''
      jar_library(
        name='compiled_scala',
        dependencies=[
          ':mybird',
        ]
      )
      '''))

    self.add_to_build_file('src/thrift/example', dedent('''
      scala_library(
        name='compiled_scala_user',
        dependencies=[
          ':compiled_scala'
        ],
        sources=['1.scala'],
      )
      '''))

    add_to_build_file('src/thrift/dependent', 'my-example', deps=['src/thrift/example:mybird'])

    self.add_to_build_file('src/java/example', dedent('''
      jar_library(
        name='mybird-jars',
        jars=[
          jar(org='com', name='twitter')
        ],
      )
      '''))

    #External Dependency tests
    self.add_to_build_file('src/java/example', dedent('''
      java_library(
        name='mybird',
        dependencies=[':mybird-jars'],
        sources=['1.java'],
      )
      '''))

    self.add_to_build_file('src/java/example', dedent('''
      java_library(
        name='example2',
        dependencies=[
          ':mybird',
        ],
        sources=['2.java']
      )
      '''))

  def test_roots(self):
    self.assert_console_output(
      'overlaps/BUILD:two',
      targets=[self.target('common/c')],
      extra_targets=[self.target('common/a')]
    )

  def test_normal(self):
    self.assert_console_output(
      'overlaps/BUILD:two',
      targets=[self.target('common/c')]
    )

  def test_closed(self):
    self.assert_console_output(
      'overlaps/BUILD:two',
      'common/c/BUILD:c',
      args=['--test-closed'],
      targets=[self.target('common/c')]
    )

  def test_transitive(self):
    self.assert_console_output(
      'overlaps/BUILD:one',
      'overlaps/BUILD:three',
      'overlaps/BUILD:four',
      'overlaps/BUILD:five',
      args=['--test-transitive'],
      targets=[self.target('common/b')]
    )

  def test_nodups_dependees(self):
    self.assert_console_output(
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      targets=[
        self.target('common/a'),
        self.target('overlaps:one')
      ],
    )

  def test_nodups_roots(self):
    targets = [self.target('common/c')] * 2
    self.assertEqual(2, len(targets))
    self.assert_console_output(
      'overlaps/BUILD:two',
      'common/c/BUILD:c',
      args=['--test-closed'],
      targets=targets
    )

  def test_aliasing(self):
    self.assert_console_output(
      'overlaps/BUILD:five',
      targets=[self.target('overlaps:four')]
    )

  def test_depeendees_type(self):
    self._set_up_mocks(PythonTests, ["%s/tests" % get_buildroot()])
    self.assert_console_output(
      'tests/d/BUILD:d',
      args=['--test-type=python_tests'],
      targets=[self.target('common/d')]
    )

  def test_empty_depeendees_type(self):
    self._set_up_mocks(Dependencies, [])
    self.assert_console_raises(
      TaskError,
      args=['--test-type=dependencies'],
      targets=[self.target('common/d')]
    )

  def test_compile_idls(self):
    self.assert_console_output(
      'src/thrift/dependent/BUILD:my-example',
      'src/thrift/example/BUILD:compiled_scala',
      targets=[
        self.target('src/thrift/example:mybird'),
      ],
    )

  def test_external_dependency(self):
    self.assert_console_output(
      'src/java/example/BUILD:example2',
       targets=[self.target('src/java/example:mybird')]
    )

  def test_resources_dependees(self):
    self.assert_console_output(
      'src/java/a/BUILD:a_java',
       targets=[self.target('resources/a:a_resources')]
    )

  def _set_up_mocks(self, class_type, src_roots):
    self.mox.StubOutWithMock(SourceRoot, 'roots')
    SourceRoot.roots(class_type).AndReturn(src_roots)
    self.mox.ReplayAll()
