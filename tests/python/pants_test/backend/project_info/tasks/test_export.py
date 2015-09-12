# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from textwrap import dedent

from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.targets.resources import Resources
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.java_tests import JavaTests
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.project_info.tasks.export import Export
from pants.backend.python.register import build_file_aliases as register_python
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants_test.subsystem.subsystem_util import subsystem_instance
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class ProjectInfoTest(ConsoleTaskTestBase):

  @classmethod
  def task_type(cls):
    return Export

  @property
  def alias_groups(self):
    return register_core().merge(register_jvm()).merge(register_python())

  def setUp(self):
    super(ProjectInfoTest, self).setUp()

    self.set_options_for_scope('jvm-platform',
                               default_platform='java6',
                               platforms= {
                                 'java6': {'source': '1.6', 'target': '1.6'}
                               })

    with subsystem_instance(ScalaPlatform):
      self.make_target(':scala-library',
                       JarLibrary,
                       jars=[JarDependency('org.scala-lang', 'scala-library', '2.10.5')])

      self.make_target(
        'project_info:first',
        target_type=Dependencies,
      )

      jar_lib = self.make_target(
        'project_info:jar_lib',
        target_type=JarLibrary,
        jars=[JarDependency('org.apache', 'apache-jar', '12.12.2012')],
      )

      self.make_target(
        'java/project_info:java_lib',
        target_type=JavaLibrary,
        sources=['com/foo/Bar.java', 'com/foo/Baz.java'],
      )

      self.make_target(
        'project_info:third',
        target_type=ScalaLibrary,
        dependencies=[jar_lib],
        java_sources=['java/project_info:java_lib'],
        sources=['com/foo/Bar.scala', 'com/foo/Baz.scala'],
      )

      self.make_target(
        'project_info:globular',
        target_type=ScalaLibrary,
        dependencies=[jar_lib],
        java_sources=['java/project_info:java_lib'],
        sources=['com/foo/*.scala'],
      )

      self.make_target(
        'project_info:jvm_app',
        target_type=JvmApp,
        dependencies=[jar_lib],
      )

      self.make_target(
        'project_info:jvm_target',
        target_type=ScalaLibrary,
        dependencies=[jar_lib],
        sources=['this/is/a/source/Foo.scala', 'this/is/a/source/Bar.scala'],
      )

      test_resource = self.make_target(
        'project_info:test_resource',
        target_type=Resources,
        sources=['y_resource', 'z_resource'],
      )

      self.make_target(
        'project_info:java_test',
        target_type=JavaTests,
        dependencies=[jar_lib],
        sources=['this/is/a/test/source/FooTest.scala'],
        resources=[test_resource.address.spec],
      )

      jvm_binary = self.make_target(
        'project_info:jvm_binary',
        target_type=JvmBinary,
        dependencies=[jar_lib],
      )

      self.make_target(
        'project_info:top_dependency',
        target_type=Dependencies,
        dependencies=[jvm_binary],
      )

      src_resource = self.make_target(
        'project_info:resource',
        target_type=Resources,
        sources=['a_resource', 'b_resource'],
      )

      self.make_target(
          'project_info:target_type',
          target_type=ScalaLibrary,
          dependencies=[jvm_binary],
          resources=[src_resource.address.spec],
      )

      self.make_target(
        'project_info:unrecognized_target_type',
        target_type=JvmTarget,
      )

      SourceRoot.register(os.path.realpath(os.path.join(self.build_root, 'src')),
                          PythonLibrary)

      self.add_to_build_file('src/x/BUILD', '''
         python_library(name="x", sources=globs("*.py"))
      '''.strip())

      self.add_to_build_file('src/y/BUILD', dedent('''
        python_library(name="y", sources=rglobs("*.py"))
        python_library(name="y2", sources=rglobs("subdir/*.py"))
        python_library(name="y3", sources=rglobs("Test*.py"))
      '''))

      self.add_to_build_file('src/z/BUILD', '''
        python_library(name="z", sources=zglobs("**/*.py"))
      '''.strip())

      self.add_to_build_file('src/exclude/BUILD', '''
        python_library(name="exclude", sources=globs("*.py", exclude=[['foo.py']]))
      '''.strip())

  def test_source_globs_py(self):
    result = get_json(self.execute_console_task(
      options=dict(globs=True),
      targets=[self.target('src/x')]
    ))

    self.assertEqual(
      {'globs': ['src/x/*.py']},
      result['targets']['src/x:x']['globs']
    )

  def test_source_globs_java(self):
    result = get_json(self.execute_console_task(
      options=dict(globs=True),
      targets=[self.target('project_info:globular')]
    ))

    self.assertEqual(
      {'globs' : ['project_info/com/foo/*.scala']},
      result['targets']['project_info:globular']['globs']
    )

  def test_without_dependencies(self):
    result = get_json(self.execute_console_task(
      targets=[self.target('project_info:first')]
    ))
    self.assertEqual({}, result['libraries'])

  def test_version(self):
    result = get_json(self.execute_console_task(
      targets=[self.target('project_info:first')]
    ))
    self.assertEqual('1.0.4', result['version'])

  def test_sources(self):
    result = get_json(self.execute_console_task(
      options=dict(sources=True),
      targets=[self.target('project_info:third')]
    ))

    self.assertEqual(
      ['project_info/com/foo/Bar.scala',
       'project_info/com/foo/Baz.scala',
      ],
      sorted(result['targets']['project_info:third']['sources'])
    )

  def test_with_dependencies(self):
    result = get_json(self.execute_console_task(
      targets=[self.target('project_info:third')]
    ))

    self.assertEqual(
      sorted([
        ':scala-library',
        'java/project_info:java_lib',
        'project_info:jar_lib'
      ]),
      sorted(result['targets']['project_info:third']['targets'])
    )
    self.assertEqual(sorted(['org.scala-lang:scala-library:2.10.5',
                             'org.apache:apache-jar:12.12.2012']),
                     sorted(result['targets']['project_info:third']['libraries']))

    self.assertEqual(1, len(result['targets']['project_info:third']['roots']))
    source_root = result['targets']['project_info:third']['roots'][0]
    self.assertEqual('com.foo', source_root['package_prefix'])
    self.assertEqual(
      '{0}/project_info/com/foo'.format(self.build_root),
      source_root['source_root']
    )

  def test_jvm_app(self):
    result = get_json(self.execute_console_task(
      targets=[self.target('project_info:jvm_app')]
    ))
    self.assertEqual(['org.apache:apache-jar:12.12.2012'],
                     result['targets']['project_info:jvm_app']['libraries'])

  def test_jvm_target(self):
    self.maxDiff = None
    result = get_json(self.execute_console_task(
      targets=[self.target('project_info:jvm_target')],
    ))
    jvm_target = result['targets']['project_info:jvm_target']
    expected_jvm_target = {
      'excludes': [],
      'globs': {'globs': ['project_info/this/is/a/source/Foo.scala',
                          'project_info/this/is/a/source/Bar.scala']},
      'libraries': ['org.apache:apache-jar:12.12.2012', 'org.scala-lang:scala-library:2.10.5'],
      'is_code_gen': False,
      'targets': ['project_info:jar_lib', ':scala-library'],
      'roots': [
         {
           'source_root': '{root}/project_info/this/is/a/source'.format(root=self.build_root),
           'package_prefix': 'this.is.a.source'
         },
      ],
      'target_type': 'SOURCE',
      'pants_target_type': 'scala_library',
      'platform': 'java6',
    }
    self.assertEqual(jvm_target, expected_jvm_target)

  def test_no_libraries(self):
    result = get_json(self.execute_console_task(
      options=dict(libraries=False),
      targets=[self.target('project_info:java_test')]
    ))
    self.assertEqual([],
                     result['targets']['project_info:java_test']['libraries'])

  def test_java_test(self):
    result = get_json(self.execute_console_task(
      targets=[self.target('project_info:java_test')]
    ))
    self.assertEqual('TEST', result['targets']['project_info:java_test']['target_type'])
    self.assertEqual(['org.apache:apache-jar:12.12.2012'],
                     result['targets']['project_info:java_test']['libraries'])
    self.assertEqual('TEST_RESOURCE',
                     result['targets']['project_info:test_resource']['target_type'])

  def test_jvm_binary(self):
    result = get_json(self.execute_console_task(
      targets=[self.target('project_info:jvm_binary')]
    ))
    self.assertEqual(['org.apache:apache-jar:12.12.2012'],
                     result['targets']['project_info:jvm_binary']['libraries'])

  def test_top_dependency(self):
    result = get_json(self.execute_console_task(
      targets=[self.target('project_info:top_dependency')]
    ))
    self.assertEqual([], result['targets']['project_info:top_dependency']['libraries'])
    self.assertEqual(['project_info:jvm_binary'],
                     result['targets']['project_info:top_dependency']['targets'])

  def test_format_flag(self):
    result = self.execute_console_task(
      targets=[self.target('project_info:third')],
      options={'formatted': False},
    )
    # confirms only one line of output, which is what -format should produce
    self.assertEqual(1, len(result))

  def test_target_types(self):
    result = get_json(self.execute_console_task(
      targets=[self.target('project_info:target_type')]
    ))
    self.assertEqual('SOURCE',
                     result['targets']['project_info:target_type']['target_type'])
    self.assertEqual('RESOURCE', result['targets']['project_info:resource']['target_type'])

  def test_target_platform(self):
    result = get_json(self.execute_console_task(
      targets=[self.target('project_info:target_type')],
    ))
    self.assertEqual('java6',
                     result['targets']['project_info:target_type']['platform'])

  def test_output_file(self):
    outfile = os.path.join(self.build_root, '.pants.d', 'test')
    self.execute_console_task(targets=[self.target('project_info:target_type')],
                              options={'output_file': outfile})
    self.assertTrue(os.path.exists(outfile))

  def test_output_file_error(self):
    with self.assertRaises(TaskError):
      self.execute_console_task(targets=[self.target('project_info:target_type')],
                                options={'output_file': self.build_root})

  def test_unrecognized_target_type(self):
    with self.assertRaises(TaskError):
      self.execute_console_task(targets=[self.target('project_info:unrecognized_target_type')])

  def test_source_exclude(self):
    result = get_json(self.execute_console_task(
      options=dict(globs=True),
      targets=[self.target('src/exclude')]
    ))

    self.assertEqual(
      {'globs': ['src/exclude/*.py'],
       'exclude': [{
         'globs': ['src/exclude/foo.py']
       }],
     },
      result['targets']['src/exclude:exclude']['globs']
    )

  def test_source_rglobs(self):
    result = get_json(self.execute_console_task(
      options=dict(globs=True),
      targets=[self.target('src/y')]
    ))

    self.assertEqual(
      {'globs': ['src/y/**/*.py', 'src/y/*.py']},
      result['targets']['src/y:y']['globs']
    )

  def test_source_rglobs_subdir(self):
    result = get_json(self.execute_console_task(
      options=dict(globs=True),
      targets=[self.target('src/y:y2')]
    ))

    self.assertEqual(
      {'globs': ['src/y/subdir/**/*.py', 'src/y/subdir/*.py']},
      result['targets']['src/y:y2']['globs']
    )

  def test_source_rglobs_noninitial(self):
    result = get_json(self.execute_console_task(
      options=dict(globs=True),
      targets=[self.target('src/y:y3')]
    ))

    self.assertEqual(
      {'globs': ['src/y/Test*.py']},
      result['targets']['src/y:y3']['globs']
    )

  def test_source_zglobs(self):
    result = get_json(self.execute_console_task(
      options=dict(globs=True),
      targets=[self.target('src/z')]
    ))

    self.assertEqual(
      {'globs': ['src/z/**/*.py']},
      result['targets']['src/z:z']['globs']
    )


def get_json(lines):
  return json.loads(''.join(lines))
