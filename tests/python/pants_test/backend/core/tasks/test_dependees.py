# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.targets.resources import Resources
from pants.backend.core.tasks.dependees import ReverseDepmap
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class BaseReverseDepmapTest(ConsoleTaskTestBase):

  @classmethod
  def task_type(cls):
    return ReverseDepmap

  def assert_console_output(self, *args, **kwargs):
    # Ensure that the globally-registered spec_excludes option is set, as Dependees consults it.
    options = {'spec_excludes': []}
    if 'options' in kwargs:
      options.update(kwargs['options'])
    kwargs['options'] = options
    return super(BaseReverseDepmapTest, self).assert_console_output(*args, **kwargs)


class ReverseDepmapEmptyTest(BaseReverseDepmapTest):

  def test(self):
    self.assert_console_output(targets=[])


class ReverseDepmapTest(BaseReverseDepmapTest):

  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'target': Dependencies,
        'jar_library': JarLibrary,
        'java_library': JavaLibrary,
        'java_thrift_library': JavaThriftLibrary,
        'python_library': PythonLibrary,
        'python_tests': PythonTests,
        'resources': Resources,
      },
      objects={
        'jar': JarDependency,
        'scala_jar': ScalaJarDependency,
      }
    )

  def setUp(self):
    super(ReverseDepmapTest, self).setUp()

    def add_to_build_file(path, name, alias=False, deps=()):
      self.add_to_build_file(path, dedent("""
          {type}(name='{name}',
            dependencies=[{deps}]
          )
          """.format(
        type='target' if alias else 'python_library',
        name=name,
        deps=','.join("'{0}'".format(dep) for dep in list(deps)))
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

    self.add_to_build_file('resources/a', dedent("""
      resources(
        name='a_resources',
        sources=['a.resource']
      )
    """))

    self.add_to_build_file('src/java/a', dedent("""
      java_library(
        name='a_java',
        resources=['resources/a:a_resources']
      )
    """))

    #Compile idl tests
    self.add_to_build_file('src/thrift/example', dedent("""
      java_thrift_library(
        name='mybird',
        compiler='scrooge',
        language='scala',
        sources=['1.thrift']
      )
      """))

    self.add_to_build_file('src/thrift/example', dedent("""
      target(
        name='compiled_scala',
        dependencies=[
          ':mybird',
        ]
      )
      """))

    self.add_to_build_file('src/thrift/example', dedent("""
      java_library(
        name='compiled_java_user',
        dependencies=[
          ':compiled_scala'
        ],
        sources=['1.java'],
      )
      """))

    add_to_build_file('src/thrift/dependent', 'my-example', deps=['src/thrift/example:mybird'])

    self.add_to_build_file('src/java/example', dedent("""
      jar_library(
        name='mybird-jars',
        jars=[
          jar(org='com', name='twitter')
        ],
      )
      """))

    #External Dependency tests
    self.add_to_build_file('src/java/example', dedent("""
      java_library(
        name='mybird',
        dependencies=[':mybird-jars'],
        sources=['1.java'],
      )
      """))

    self.add_to_build_file('src/java/example', dedent("""
      java_library(
        name='example2',
        dependencies=[
          ':mybird',
        ],
        sources=['2.java']
      )
      """))

  def test_roots(self):
    self.assert_console_output(
      'overlaps:two',
      targets=[self.target('common/c')],
      extra_targets=[self.target('common/a')]
    )

  def test_normal(self):
    self.assert_console_output(
      'overlaps:two',
      targets=[self.target('common/c')]
    )

  def test_closed(self):
    self.assert_console_output(
      'overlaps:two',
      'common/c:c',
      targets=[self.target('common/c')],
      options={'closed': True}
    )

  def test_transitive(self):
    self.assert_console_output(
      'overlaps:one',
      'overlaps:three',
      'overlaps:four',
      'overlaps:five',
      targets=[self.target('common/b')],
      options={'transitive': True}
    )

  def test_nodups_dependees(self):
    self.assert_console_output(
      'overlaps:two',
      'overlaps:three',
      targets=[
        self.target('common/a'),
        self.target('overlaps:one')
      ],
    )

  def test_nodups_roots(self):
    targets = [self.target('common/c')] * 2
    self.assertEqual(2, len(targets))
    self.assert_console_output(
      'overlaps:two',
      'common/c:c',
      targets=targets,
      options={'closed': True}
    )

  def test_aliasing(self):
    self.assert_console_output(
      'overlaps:five',
      targets=[self.target('overlaps:four')]
    )

  def test_compile_idls(self):
    self.assert_console_output(
      'src/thrift/dependent:my-example',
      'src/thrift/example:compiled_scala',
      targets=[
        self.target('src/thrift/example:mybird'),
      ],
    )

  def test_external_dependency(self):
    self.assert_console_output(
      'src/java/example:example2',
       targets=[self.target('src/java/example:mybird')]
    )

  def test_resources_dependees(self):
    self.assert_console_output(
      'src/java/a:a_java',
       targets=[self.target('resources/a:a_resources')]
    )

  def test_with_spec_excludes(self):
    self.assert_console_output(
      'overlaps:one',
      'overlaps:two',
      'overlaps:three',
      targets=[self.target('common/a')]
    )

    self.assert_console_output(
      targets=[self.target('common/a')],
      options={'spec_excludes': ['overlaps']}
    )
