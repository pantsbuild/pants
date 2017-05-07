# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import textwrap
from contextlib import contextmanager
from textwrap import dedent

from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.subsystems.junit import JUnit
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.project_info.tasks.export import Export
from pants.backend.python.register import build_file_aliases as register_python
from pants.base.exceptions import TaskError
from pants.build_graph.register import build_file_aliases as register_core
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.java.distribution.distribution import DistributionLocator
from pants.java.jar.jar_dependency import JarDependency
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import chmod_plus_x, safe_open
from pants.util.osutil import get_os_name, normalize_os_name
from pants_test.backend.python.tasks.interpreter_cache_test_mixin import InterpreterCacheTestMixin
from pants_test.subsystem.subsystem_util import init_subsystems
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class ExportTest(InterpreterCacheTestMixin, ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return Export

  @property
  def alias_groups(self):
    return register_core().merge(register_jvm()).merge(register_python())

  def setUp(self):
    super(ExportTest, self).setUp()

    # We need an initialized ScalaPlatform in order to make ScalaLibrary targets below.
    scala_options = {
      ScalaPlatform.options_scope: {
        'version': 'custom'
      }
    }
    init_subsystems([JUnit, ScalaPlatform], scala_options)

    self.make_target(':scala-library',
                     JarLibrary,
                     jars=[JarDependency('org.scala-lang', 'scala-library', '2.10.5')])

    self.make_target(
      'project_info:first',
      target_type=Target,
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
      target_type=JUnitTests,
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
      target_type=Target,
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
        sources=[],
        resources=[src_resource.address.spec],
    )

    self.make_target(
      'project_info:unrecognized_target_type',
      target_type=JvmTarget,
    )

    self.add_to_build_file('src/python/x/BUILD', """
       python_library(name="x", sources=globs("*.py"))
    """.strip())

    self.add_to_build_file('src/python/y/BUILD', dedent("""
      python_library(name="y", sources=rglobs("*.py"))
      python_library(name="y2", sources=rglobs("subdir/*.py"))
      python_library(name="y3", sources=rglobs("Test*.py"))
    """))

    self.add_to_build_file('src/python/z/BUILD', """
      python_library(name="z", sources=zglobs("**/*.py"))
    """.strip())

    self.add_to_build_file('src/python/exclude/BUILD', """
      python_library(name="exclude", sources=globs("*.py", exclude=[['foo.py']]))
    """.strip())

    self.add_to_build_file('src/BUILD', """
      target(name="alias")
    """.strip())

  def execute_export(self, *specs, **options_overrides):
    options = {
      JvmPlatform.options_scope: {
        'default_platform': 'java6',
        'platforms': {
          'java6': {'source': '1.6', 'target': '1.6'}
        }
      },
    }
    options.update(options_overrides)
    context = self.context(options=options, target_roots=[self.target(spec) for spec in specs],
                           for_subsystems=[JvmPlatform])
    context.products.safe_create_data('compile_classpath',
                                      init_func=ClasspathProducts.init_func(self.pants_workdir))
    task = self.create_task(context)
    return list(task.console_output(list(task.context.targets()),
                                    context.products.get_data('compile_classpath')))

  def execute_export_json(self, *specs, **options):
    return json.loads(''.join(self.execute_export(*specs, **options)))

  def test_source_globs_py(self):
    self.set_options(globs=True)
    result = self.execute_export_json('src/python/x')

    self.assertEqual(
      {'globs': ['src/python/x/*.py']},
      result['targets']['src/python/x:x']['globs']
    )

  def test_source_globs_java(self):
    self.set_options(globs=True)
    result = self.execute_export_json('project_info:globular')

    self.assertEqual(
      {'globs' : ['project_info/com/foo/*.scala']},
      result['targets']['project_info:globular']['globs']
    )

  def test_source_globs_alias(self):
    self.set_options(globs=True)
    result = self.execute_export_json('src:alias')

    self.assertEqual(
        {'globs': []},
      result['targets']['src:alias']['globs']
    )

  def test_without_dependencies(self):
    result = self.execute_export_json('project_info:first')
    self.assertEqual({}, result['libraries'])

  def test_version(self):
    result = self.execute_export_json('project_info:first')
    # If you have to update this test, make sure export.md is updated with changelog notes
    self.assertEqual('1.0.9', result['version'])

  def test_sources(self):
    self.set_options(sources=True)
    result = self.execute_export_json('project_info:third')

    self.assertEqual(
      ['project_info/com/foo/Bar.scala',
       'project_info/com/foo/Baz.scala',
      ],
      sorted(result['targets']['project_info:third']['sources'])
    )

  def test_with_dependencies(self):
    result = self.execute_export_json('project_info:third')

    self.assertEqual(
      sorted([
        '//:scala-library',
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
    result = self.execute_export_json('project_info:jvm_app')
    self.assertEqual(['org.apache:apache-jar:12.12.2012'],
                     result['targets']['project_info:jvm_app']['libraries'])

  def test_jvm_target(self):
    self.maxDiff = None
    result = self.execute_export_json('project_info:jvm_target')
    jvm_target = result['targets']['project_info:jvm_target']
    expected_jvm_target = {
      'excludes': [],
      'globs': {'globs': ['project_info/this/is/a/source/Foo.scala',
                          'project_info/this/is/a/source/Bar.scala']},
      'libraries': ['org.apache:apache-jar:12.12.2012', 'org.scala-lang:scala-library:2.10.5'],
      'id': 'project_info.jvm_target',
      'is_code_gen': False,
      'targets': ['project_info:jar_lib', '//:scala-library'],
      'is_synthetic': False,
      'is_target_root': True,
      'roots': [
         {
           'source_root': '{root}/project_info/this/is/a/source'.format(root=self.build_root),
           'package_prefix': 'this.is.a.source'
         },
      ],
      'scope' : 'default',
      'target_type': 'SOURCE',
      'transitive' : True,
      'pants_target_type': 'scala_library',
      'platform': 'java6',
    }
    self.assertEqual(jvm_target, expected_jvm_target)

  def test_no_libraries(self):
    self.set_options(libraries=False)
    result = self.execute_export_json('project_info:java_test')
    self.assertEqual([],
                     result['targets']['project_info:java_test']['libraries'])

  def test_java_test(self):
    result = self.execute_export_json('project_info:java_test')
    self.assertEqual('TEST', result['targets']['project_info:java_test']['target_type'])
    # Note that the junit dep gets auto-injected via the JUnit subsystem.
    self.assertEqual(['org.apache:apache-jar:12.12.2012',
                      'junit:junit:{}'.format(JUnit.LIBRARY_REV)],
                     result['targets']['project_info:java_test']['libraries'])
    self.assertEqual('TEST_RESOURCE',
                     result['targets']['project_info:test_resource']['target_type'])

  def test_jvm_binary(self):
    result = self.execute_export_json('project_info:jvm_binary')
    self.assertEqual(['org.apache:apache-jar:12.12.2012'],
                     result['targets']['project_info:jvm_binary']['libraries'])

  def test_top_dependency(self):
    result = self.execute_export_json('project_info:top_dependency')
    self.assertEqual([], result['targets']['project_info:top_dependency']['libraries'])
    self.assertEqual(['project_info:jvm_binary'],
                     result['targets']['project_info:top_dependency']['targets'])

  def test_format_flag(self):
    self.set_options(formatted=False)
    result = self.execute_export('project_info:third')
    # confirms only one line of output, which is what -format should produce
    self.assertEqual(1, len(result))

  def test_target_types(self):
    result = self.execute_export_json('project_info:target_type')
    self.assertEqual('SOURCE',
                     result['targets']['project_info:target_type']['target_type'])
    self.assertEqual('RESOURCE', result['targets']['project_info:resource']['target_type'])

  def test_target_platform(self):
    result = self.execute_export_json('project_info:target_type')
    self.assertEqual('java6',
                     result['targets']['project_info:target_type']['platform'])

  def test_output_file(self):
    outfile = os.path.join(self.build_root, '.pants.d', 'test')
    self.set_options(output_file=outfile)
    self.execute_export('project_info:target_type')
    self.assertTrue(os.path.exists(outfile))

  def test_output_file_error(self):
    self.set_options(output_file=self.build_root)
    with self.assertRaises(TaskError):
      self.execute_export('project_info:target_type')

  def test_source_exclude(self):
    self.set_options(globs=True)
    result = self.execute_export_json('src/python/exclude')

    self.assertEqual(
      {'globs': ['src/python/exclude/*.py'],
       'exclude': [{
         'globs': ['src/python/exclude/foo.py']
       }],
     },
      result['targets']['src/python/exclude:exclude']['globs']
    )

  def test_source_rglobs(self):
    self.set_options(globs=True)
    result = self.execute_export_json('src/python/y')

    self.assertEqual(
      {'globs': ['src/python/y/**/*.py']},
      result['targets']['src/python/y:y']['globs']
    )

  def test_source_rglobs_subdir(self):
    self.set_options(globs=True)
    result = self.execute_export_json('src/python/y:y2')

    self.assertEqual(
      {'globs': ['src/python/y/subdir/**/*.py']},
      result['targets']['src/python/y:y2']['globs']
    )

  def test_source_rglobs_noninitial(self):
    self.set_options(globs=True)
    result = self.execute_export_json('src/python/y:y3')

    self.assertEqual(
      {'globs': ['src/python/y/Test*.py']},
      result['targets']['src/python/y:y3']['globs']
    )

  def test_source_zglobs(self):
    self.set_options(globs=True)
    result = self.execute_export_json('src/python/z')

    self.assertEqual(
      {'globs': ['src/python/z/**/*.py']},
      result['targets']['src/python/z:z']['globs']
    )

  # TODO: Delete this test in 1.5.0.dev0, once we remove support for resources=.
  def test_synthetic_target(self):
    # Create a BUILD file then add itself as resources
    self.add_to_build_file('src/python/alpha/BUILD', """
        python_library(name="alpha", sources=zglobs("**/*.py"), resources=["BUILD"])
      """.strip())

    result = self.execute_export_json('src/python/alpha')
    self.assertTrue(result['targets']['src/python/alpha:alpha_synthetic_resources'])
    # But not the origin target
    self.assertFalse(result['targets']['src/python/alpha:alpha']['is_synthetic'])

  @contextmanager
  def fake_distribution(self, version):
    with temporary_dir() as java_home:
      path = os.path.join(java_home, 'bin/java')
      with safe_open(path, 'w') as fp:
        fp.write(textwrap.dedent("""
          #!/bin/sh
          echo java.version={version}
        """.format(version=version)).strip())
      chmod_plus_x(path)
      yield java_home

  def test_preferred_jvm_distributions(self):
    with self.fake_distribution(version='9999') as strict_home:
      with self.fake_distribution(version='10000') as non_strict_home:
        options = {
          JvmPlatform.options_scope: {
            'default_platform': 'java9999',
            'platforms': {
              'java9999': {'target': '9999'},
              'java10000': {'target': '10000'}
            }
          },
          DistributionLocator.options_scope: {
            'paths': {
              normalize_os_name(get_os_name()): [
                strict_home,
                non_strict_home
              ]
            }
          }
        }

        export_json = self.execute_export_json(**options)
        self.assertEqual({'strict': strict_home, 'non_strict': non_strict_home},
                         export_json['preferred_jvm_distributions']['java9999'])
