# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)
import json

from textwrap import dedent

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.targets.resources import Resources
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.java_tests import JavaTests
from pants.backend.jvm.targets.jvm_binary import Bundle, JvmApp, JvmBinary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.depmap import Depmap
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TaskError
from pants_test.tasks.test_base import ConsoleTaskTest


class BaseDepmapTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return Depmap


class DepmapTest(BaseDepmapTest):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'dependencies': Dependencies,
        'jar_library': JarLibrary,
        'java_library': JavaLibrary,
        'jvm_app': JvmApp,
        'jvm_binary': JvmBinary,
        'python_binary': PythonBinary,
        'python_library': PythonLibrary,
        'resources': Resources,
      },
      objects={
        'pants': lambda x: x,
      },
      context_aware_object_factories={
        'bundle': Bundle,
      }
    )

  def setUp(self):
    super(DepmapTest, self).setUp()

    def add_to_build_file(path, name, type, deps=(), **kwargs):
      self.add_to_build_file(path, dedent('''
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
      self.add_to_build_file(path, dedent('''
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
      self.add_to_build_file(path, dedent('''
          %(type)s(name='%(name)s',
            dependencies=[pants('%(binary)s')],
            bundles=%(deps)s
          )
          ''' % dict(
        type=type,
        name=name,
        binary=binary,
        deps=deps)
      ))

    add_to_build_file('common/a', 'a', 'dependencies')
    add_to_build_file('common/b', 'b', 'jar_library')
    self.add_to_build_file('common/c', dedent('''
      java_library(name='c',
        sources=[],
      )
    '''))
    add_to_build_file('common/d', 'd', 'python_library')
    create_python_binary_target('common/e', 'e', 'common.e.entry', 'python_binary')
    add_to_build_file('common/f', 'f', 'jvm_binary')
    add_to_build_file('common/g', 'g', 'jvm_binary', deps=['common/f:f'])
    self.create_dir('common/h')
    self.create_file('common/h/common.f')
    create_jvm_app('common/h', 'h', 'jvm_app', 'common/f:f', "bundle().add('common.f')")
    self.create_dir('common/i')
    self.create_file('common/i/common.g')
    create_jvm_app('common/i', 'i', 'jvm_app', 'common/g:g', "bundle().add('common.g')")
    add_to_build_file('overlaps', 'one', 'jvm_binary', deps=['common/h', 'common/i'])
    self.add_to_build_file('overlaps', dedent('''
      java_library(name='two',
        dependencies=[pants('overlaps:one')],
        sources=[],
      )
    '''))
    self.add_to_build_file('resources/a', dedent('''
      resources(
        name='a_resources',
        sources=['a.resource']
      )
    '''))
    self.add_to_build_file('src/java/a', dedent('''
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

  def test_java_library(self):
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
      '  internal-common.i.i',
      '    internal-common.g.g',
      '      internal-common.f.f',
      '  internal-common.h.h',
      '    *internal-common.f.f',
      targets=[self.target('overlaps:one')]
    )

  def test_overlaps_two(self):
    self.assert_console_output(
      'internal-overlaps.two',
      '  internal-overlaps.one',
      '    internal-common.i.i',
      '      internal-common.g.g',
      '        internal-common.f.f',
      '    internal-common.h.h',
      '      *internal-common.f.f',
      targets=[self.target('overlaps:two')]
    )

  def test_overlaps_two_minimal(self):
    self.assert_console_output(
      'internal-overlaps.two',
      '  internal-overlaps.one',
      '    internal-common.i.i',
      '      internal-common.g.g',
      '        internal-common.f.f',
      '    internal-common.h.h',
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


class ProjectInfoTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return Depmap

  def setUp(self):
    super(ProjectInfoTest, self).setUp()

    first = self.make_target(
      'project_info:first',
      target_type=JarLibrary,
    )

    second = self.make_target(
      'project_info:second',
      target_type=JarLibrary,
      jars=[JarDependency('org.apache', 'apache-jar', '12.12.2012')],
    )

    third = self.make_target(
      'project_info:third',
      target_type=ScalaLibrary,
      dependencies=[second],
    )

    jvm_app = self.make_target(
      'project_info:jvm_app',
      target_type=JvmApp,
      dependencies=[second],
    )

    jvm_target = self.make_target(
      'project_info:jvm_target',
      target_type=JvmTarget,
      dependencies=[second],
      sources=['this/is/a/source/Foo.scala', 'this/is/a/source/Bar.scala'],

    )

    java_tests = self.make_target(
      'project_info:java_test',
      target_type=JavaTests,
      dependencies=[second],
    )

    jvm_binary = self.make_target(
      'project_info:jvm_binary',
      target_type=JvmBinary,
      dependencies=[second],
    )

  def test_without_dependencies(self):
    result = get_json(self.execute_console_task(
      args=['--test-project-info'],
      targets=[self.target('project_info:first')]
    ))
    self.assertEqual({}, result['libraries'])

  def test_with_dependencies(self):
    result = get_json(self.execute_console_task(
      args=['--test-project-info'],
      targets=[self.target('project_info:third')]
    ))
    self.assertEqual(['org.apache:apache-jar:12.12.2012'], result['targets']['project_info:third']['libraries'])

  def test_jvm_app(self):
    result = get_json(self.execute_console_task(
      args=['--test-project-info'],
      targets=[self.target('project_info:jvm_app')]
    ))
    self.assertEqual(['org.apache:apache-jar:12.12.2012'], result['targets']['project_info:jvm_app']['libraries'])

  def test_jvm_target(self):
    result = get_json(self.execute_console_task(
      args=['--test-project-info'],
      targets=[self.target('project_info:jvm_target')]
    ))
    self.assertIn('/this/is/a', result['targets']['project_info:jvm_target']['roots'][0]['source_root'])
    self.assertEqual('this.is.a.source', result['targets']['project_info:jvm_target']['roots'][0]['package_prefix'])
    self.assertEqual(['org.apache:apache-jar:12.12.2012'], result['targets']['project_info:jvm_target']['libraries'])

  def test_java_test(self):
    result = get_json(self.execute_console_task(
      args=['--test-project-info'],
      targets=[self.target('project_info:java_test')]
    ))
    self.assertEqual(True, result['targets']['project_info:java_test']['test_target'])
    self.assertEqual(['org.apache:apache-jar:12.12.2012'], result['targets']['project_info:java_test']['libraries'])

  def test_jvm_binary(self):
    result = get_json(self.execute_console_task(
      args=['--test-project-info'],
      targets=[self.target('project_info:jvm_binary')]
    ))
    self.assertEqual(['org.apache:apache-jar:12.12.2012'], result['targets']['project_info:jvm_binary']['libraries'])

  def test_format_flag(self):
    result = self.execute_console_task(
      args=['--test-project-info', '--test-project-info-formatted'],
      targets=[self.target('project_info:third')]
    )
    # confirms only one line of output, which is what -format should produce
    self.assertEqual(1, len(result))


def get_json(lines):
  return json.loads(''.join(lines))
