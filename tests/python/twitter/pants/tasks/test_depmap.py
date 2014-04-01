# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

from pants.tasks.depmap import Depmap
from pants.tasks.task_error import TaskError
from pants.tasks.test_base import ConsoleTaskTest


class BaseDepmapTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return Depmap


class DepmapTest(BaseDepmapTest):
  @classmethod
  def setUpClass(cls):
    super(DepmapTest, cls).setUpClass()

    def create_target(path, name, type, deps=(), **kwargs):
      cls.create_target(path, dedent('''
          %(type)s(name='%(name)s',
            dependencies=[%(deps)s],
            %(extra)s
          )
          ''' % dict(
        type=type,
        name=name,
        deps=','.join("pants('%s')" % dep for dep in list(deps)),
        extra=('' if not kwargs else ', '.join('%s=%r' % (k, v) for k, v in kwargs.items()))
      )))

    def create_python_binary_target(path, name, entry_point, type, deps=()):
      cls.create_target(path, dedent('''
          %(type)s(name='%(name)s',
            entry_point='%(entry_point)s',
            dependencies=[%(deps)s]
          )
          ''' % dict(
        type=type,
        entry_point=entry_point,
        name=name,
        deps=','.join("pants('%s')" % dep for dep in list(deps)))
      ))

    def create_jvm_app(path, name, type, binary, deps=()):
      cls.create_target(path, dedent('''
          %(type)s(name='%(name)s',
            binary=pants('%(binary)s'),
            bundles=%(deps)s
          )
          ''' % dict(
        type=type,
        name=name,
        binary=binary,
        deps=deps)
      ))

    create_target('common/a', 'a', 'dependencies')
    create_target('common/b', 'b', 'jar_library')
    cls.create_target('common/c', dedent('''
      scala_library(name='c',
        sources=[],
      )
    '''))
    create_target('common/d', 'd', 'python_library')
    create_python_binary_target('common/e', 'e', 'common.e.entry', 'python_binary')
    create_target('common/f', 'f', 'jvm_binary')
    create_target('common/g', 'g', 'jvm_binary', deps=['common/f:f'])
    cls.create_dir('common/h')
    cls.create_file('common/h/common.f')
    create_jvm_app('common/h', 'h', 'jvm_app', 'common/f:f', "bundle().add('common.f')")
    cls.create_dir('common/i')
    cls.create_file('common/i/common.g')
    create_jvm_app('common/i', 'i', 'jvm_app', 'common/g:g', "bundle().add('common.g')")
    create_target('overlaps', 'one', 'jvm_binary', deps=['common/h', 'common/i'])
    cls.create_target('overlaps', dedent('''
      scala_library(name='two',
        dependencies=[pants('overlaps:one')],
        sources=[],
      )
    '''))
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

  def test_empty(self):
    self.assert_console_raises(
      TaskError,
      targets=[self.target('common/a')]
    )

  def test_jar_library(self):
    self.assert_console_raises(
      TaskError,
      targets=[self.target('common/b')],
    )

  def test_scala_library(self):
    self.assert_console_output(
      'internal-common.c.c',
      targets=[self.target('common/c')]
    )

  def test_python_library(self):
    self.assert_console_raises(
      TaskError,
      targets=[self.target('common/d')]
    )

  def test_python_binary(self):
    self.assert_console_raises(
      TaskError,
      targets=[self.target('common/e')]
    )

  def test_jvm_binary1(self):
    self.assert_console_output(
      'internal-common.f.f',
      targets=[self.target('common/f')]
    )

  def test_jvm_binary2(self):
    self.assert_console_output(
      'internal-common.g.g',
      '  internal-common.f.f',
      targets=[self.target('common/g')]
    )

  def test_jvm_app1(self):
    self.assert_console_output(
      'internal-common.h.h',
      '  internal-common.f.f',
      targets=[self.target('common/h')]
    )

  def test_jvm_app2(self):
    self.assert_console_output(
      'internal-common.i.i',
      '  internal-common.g.g',
      '    internal-common.f.f',
      targets=[self.target('common/i')]
    )

  def test_overlaps_one(self):
    self.assert_console_output(
      'internal-overlaps.one',
      '  internal-common.h.h',
      '    internal-common.f.f',
      '  internal-common.i.i',
      '    internal-common.g.g',
      '      *internal-common.f.f',
      targets=[self.target('overlaps:one')]
    )

  def test_overlaps_two(self):
    self.assert_console_output(
      'internal-overlaps.two',
      '  internal-overlaps.one',
      '    internal-common.h.h',
      '      internal-common.f.f',
      '    internal-common.i.i',
      '      internal-common.g.g',
      '        *internal-common.f.f',
      targets=[self.target('overlaps:two')]
    )

  def test_overlaps_two_minimal(self):
    self.assert_console_output(
      'internal-overlaps.two',
      '  internal-overlaps.one',
      '    internal-common.h.h',
      '      internal-common.f.f',
      '    internal-common.i.i',
      '      internal-common.g.g',
      targets=[self.target('overlaps:two')],
      args=['--test-minimal']
    )

  def test_multi(self):
    self.assert_console_output(
      'internal-common.g.g',
      '  internal-common.f.f',
      'internal-common.h.h',
      '  internal-common.f.f',
      'internal-common.i.i',
      '  internal-common.g.g',
      '    internal-common.f.f',
      targets=[self.target('common/g'), self.target('common/h'), self.target('common/i')]
    )

  def test_resources(self):
    self.assert_console_output(
      'internal-src.java.a.a_java',
      '  internal-resources.a.a_resources',
      targets=[self.target('src/java/a:a_java')]
    )
