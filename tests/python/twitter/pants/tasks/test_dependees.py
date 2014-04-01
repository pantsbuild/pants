# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

import mox

from pants.base.build_environment import get_buildroot
from pants.targets.python_tests import PythonTestSuite, PythonTests
from pants.targets.sources import SourceRoot
from pants.tasks import TaskError
from pants.tasks.dependees import ReverseDepmap
from pants.tasks.test_base import ConsoleTaskTest


class BaseReverseDepmapTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return ReverseDepmap


class ReverseDepmapEmptyTest(BaseReverseDepmapTest):
  def test(self):
    self.assert_console_output(targets=[])


class ReverseDepmapTest(BaseReverseDepmapTest, mox.MoxTestBase):
  @classmethod
  def setUpClass(cls):
    super(ReverseDepmapTest, cls).setUpClass()

    def create_target(path, name, alias=False, deps=()):
      cls.create_target(path, dedent('''
          %(type)s(name='%(name)s',
            dependencies=[%(deps)s]
          )
          ''' % dict(
        type='dependencies' if alias else 'python_library',
        name=name,
        deps=','.join("pants('%s')" % dep for dep in list(deps)))
      ))

    create_target('common/a', 'a', deps=['common/d'])
    create_target('common/b', 'b')
    create_target('common/c', 'c')
    create_target('common/d', 'd')
    create_target('tests/d', 'd', deps=['common/d'])
    create_target('overlaps', 'one', deps=['common/a', 'common/b'])
    create_target('overlaps', 'two', deps=['common/a', 'common/c'])
    create_target('overlaps', 'three', deps=['common/a', 'overlaps:one'])
    create_target('overlaps', 'four', alias=True, deps=['common/b'])
    create_target('overlaps', 'five', deps=['overlaps:four'])

    cls.create_target('resources/a', dedent('''
      resources(
        name='a_resources',
        sources=['a.resource']
      )
    '''))

    cls.create_target('src/java/a', dedent('''
      java_library(
        name='a_java',
        resources=[pants('resources/a:a_resources')]
      )
    '''))

    #Compile idl tests
    cls.create_target('src/thrift/example', dedent('''
      java_thrift_library(
        name='mybird',
        compiler='scrooge',
        language='scala',
        sources=['1.thrift']
      )
      '''))

    cls.create_target('src/thrift/example', dedent('''
      jar_library(
        name='compiled_scala',
        dependencies=[
          pants(':mybird')
        ]
      )
      '''))

    cls.create_target('src/thrift/example', dedent('''
      scala_library(
        name='compiled_scala_user',
        dependencies=[
          pants(':compiled_scala')
        ],
        sources=['1.scala'],
      )
      '''))

    create_target('src/thrift/dependent', 'my-example', deps=['src/thrift/example:mybird'])

    #External Dependency tests
    cls.create_target('src/java/example', dedent('''
      java_library(
        name='mybird',
        dependencies=[
          jar(org='com', name='twitter')
        ],
        sources=['1.java'],
      )
      '''))

    cls.create_target('src/java/example', dedent('''
      java_library(
        name='example2',
        dependencies=[
          pants(':mybird')
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
    self._set_up_mocks(PythonTestSuite, [])
    self.assert_console_raises(
      TaskError,
      args=['--test-type=python_test_suite'],
      targets=[self.target('common/d')]
    )

  def test_compile_idls(self):
    self.assert_console_output(
      'src/thrift/dependent/BUILD:my-example',
      'src/thrift/example/BUILD:compiled_scala',
      'src/thrift/example/BUILD:compiled_scala_user',
      targets=[
        self.target('src/thrift/example:mybird'),
      ],
    )

  def test_external_dependency(self):
    self.assert_console_output(
      'src/java/example/BUILD:example2',
       targets=[self.target('src/java/example/BUILD:mybird')]
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
