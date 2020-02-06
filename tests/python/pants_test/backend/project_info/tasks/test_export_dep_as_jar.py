# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import textwrap
from contextlib import contextmanager
from unittest.mock import MagicMock
from zipfile import ZipFile

from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.subsystems.junit import JUnit
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.resolve_subsystem import JvmResolveSubsystem
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.scoverage_platform import ScoveragePlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.bootstrap_jvm_tools import BootstrapJvmTools
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.project_info.tasks.export_dep_as_jar import ExportDepAsJar
from pants.backend.project_info.tasks.export_version import DEFAULT_EXPORT_VERSION
from pants.base.exceptions import TaskError
from pants.build_graph.address import Address
from pants.build_graph.register import build_file_aliases as register_core
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.java.distribution.distribution import DistributionLocator
from pants.java.jar.jar_dependency import JarDependency
from pants.testutil.subsystem.util import init_subsystems
from pants.testutil.task_test_base import ConsoleTaskTestBase
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import chmod_plus_x, safe_open
from pants.util.osutil import get_os_name, normalize_os_name


class ExportDepAsJarTest(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return ExportDepAsJar

  @classmethod
  def alias_groups(cls):
    return register_core().merge(register_jvm())

  # Version of the scala compiler and libraries used for this test.
  _scala_toolchain_version = '2.10.5'

  def setUp(self):
    super().setUp()

    # We need an initialized ScalaPlatform in order to make ScalaLibrary targets below.
    scala_options = {
      ScalaPlatform.options_scope: {
        'version': 'custom'
      }
    }
    init_subsystems([JUnit, ScalaPlatform, ScoveragePlatform], scala_options)

    self.make_target(
      ':jar-tool',
      JarLibrary,
      jars=[JarDependency('org.pantsbuild', 'jar-tool', '0.0.10')]
    )

    # NB: `test_has_python_requirements` will attempt to inject every possible scala compiler target
    # spec, for versions 2.10, 2.11, 2.12, and custom, and will error out if they are not
    # available. This isn't a problem when running pants on the command line, but in unit testing
    # there's probably some task or subsystem that needs to be initialized to avoid this.
    for empty_target in ['scalac', 'scala-repl', 'scala-library', 'scala-reflect', 'scalastyle']:
      for unused_scala_version in ['2_10', '2_11']:
        self.make_target(
          f':{empty_target}_{unused_scala_version}',
          Target,
        )
    self.make_target(
      ':scalac-plugin-dep',
      Target,
    )

    self.make_target(
      ':jarjar',
      JarLibrary,
      jars=[JarDependency(org='org.pantsbuild', name='jarjar', rev='1.7.2')]
    )

    self.make_target(
      ':scala-library',
      JarLibrary,
      jars=[JarDependency('org.scala-lang', 'scala-library', self._scala_toolchain_version)]
    )

    self.make_target(
      ':scalac',
      JarLibrary,
      jars=[JarDependency('org.scala-lang', 'scala-compiler', self._scala_toolchain_version)]
    )

    self.make_target(
      ':scalac_2_12',
      JarLibrary,
      jars=[JarDependency('org.scala-lang', 'scala-compiler', '2.12.8')]
    )
    self.make_target(
      ':scala-library_2_12',
      JarLibrary,
      jars=[JarDependency('org.scala-lang', 'scala-library', '2.12.8')]
    )
    self.make_target(
      ':scala-reflect_2_12',
      JarLibrary,
      jars=[JarDependency('org.scala-lang', 'scala-reflect', '2.12.8')]
    )
    self.make_target(
      ':scala-repl_2_12',
      JarLibrary,
      jars=[JarDependency('org.scala-lang', 'scala-repl', '2.12.8')]
    )
    self.make_target(
      ':scalastyle_2_12',
      Target,
    )
    self.make_target(
      ':scalastyle',
      Target,
    )


    self.make_target(
      ':scala-reflect',
      JarLibrary,
      jars=[JarDependency('org.scala-lang', 'scala-reflect', self._scala_toolchain_version)]
    )

    self.make_target(
      ':scala-repl',
      JarLibrary,
      jars=[JarDependency('org.scala-lang', 'scala-repl', self._scala_toolchain_version)]
    )

    self.make_target(
      ':nailgun-server',
      JarLibrary,
      jars=[JarDependency(org='com.martiansoftware', name='nailgun-server', rev='0.9.1'),]
    )

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

    self.jvm_target_with_sources = self.make_target(
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
      dependencies=[jar_lib, test_resource],
      sources=['this/is/a/test/source/FooTest.scala'],
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

    self.create_file('project_info/a_resource', contents='a')
    self.create_file('project_info/b_resource', contents='b')

    src_resource = self.make_target(
      'project_info:resource',
      target_type=Resources,
      sources=['a_resource', 'b_resource'],
    )

    self.make_target(
        'project_info:target_type',
        target_type=ScalaLibrary,
        dependencies=[jvm_binary, src_resource],
        sources=[],
    )

    self.make_target(
      'project_info:unrecognized_target_type',
      target_type=JvmTarget,
    )

    self.scala_with_source_dep = self.make_target(
      'project_info:scala_with_source_dep',
      target_type=ScalaLibrary,
      dependencies=[self.jvm_target_with_sources],
      sources=[],
    )

    self.linear_build_graph = self.make_linear_graph(['a', 'b', 'c', 'd', 'e'], target_type=ScalaLibrary)

  def create_runtime_classpath_for_targets(self, target):
    def path_to_zjar_with_workdir(address: Address):
      return os.path.join(self.pants_workdir, address.path_safe_spec, "z.jar")

    runtime_classpath = ClasspathProducts(self.pants_workdir)
    for dep in target.dependencies:
      runtime_classpath.add_for_target(dep, [('default', path_to_zjar_with_workdir(dep.address))])
    return runtime_classpath

  def execute_export(self, *specs, **options_overrides):
    options = {
      ScalaPlatform.options_scope: {
        'version': 'custom'
      },
      JvmResolveSubsystem.options_scope: {
        'resolver': 'ivy'
      },
      JvmPlatform.options_scope: {
        'default_platform': 'java8',
        'platforms': {
          'java8': {'source': '1.8', 'target': '1.8'}
        }
      },
    }
    options.update(options_overrides)

    BootstrapJvmTools.options_scope = 'bootstrap-jvm-tools'
    context = self.context(options=options, target_roots=[self.target(spec) for spec in specs],
                           for_subsystems=[JvmPlatform],
                           for_task_types=[BootstrapJvmTools])

    runtime_classpath = self.create_runtime_classpath_for_targets(self.scala_with_source_dep)
    context.products.safe_create_data('export_dep_as_jar_classpath',
                                      init_func=lambda: runtime_classpath)

    context.products.safe_create_data('zinc_args', init_func=lambda: MagicMock())

    bootstrap_task = BootstrapJvmTools(context, self.pants_workdir)
    bootstrap_task.execute()
    task = self.create_task(context)
    return list(task.console_output(list(task.context.targets())))

  def execute_export_json(self, *specs, **options):
    return json.loads(''.join(self.execute_export(*specs, **options)))

  def test_source_globs_java(self):
    self.set_options(globs=True)
    result = self.execute_export_json('project_info:globular')

    self.assertEqual(
      {'globs' : ['project_info/com/foo/*.scala']},
      result['targets']['project_info:globular']['globs']
    )

  def test_without_dependencies(self):
    result = self.execute_export_json('project_info:first')
    self.assertEqual({}, result['libraries'])

  def test_version(self):
    result = self.execute_export_json('project_info:first')
    # If you have to update this test, make sure export.md is updated with changelog notes
    self.assertEqual(DEFAULT_EXPORT_VERSION, result['version'])

  def test_scala_platform_custom(self):
    result = self.execute_export_json('project_info:first')
    scala_platform = result['scala_platform']
    scala_version = scala_platform['scala_version']
    self.assertEqual(scala_version, 'custom')
    scala_jars = scala_platform['compiler_classpath']
    self.assertTrue(any(self._scala_toolchain_version in jar_path for jar_path in scala_jars))

  def test_scala_platform_standard(self):
    result = self.execute_export_json('project_info:first', **{
      ScalaPlatform.options_scope: {
        'version': '2.12'
      }
    })
    scala_platform = result['scala_platform']
    scala_version = scala_platform['scala_version']
    self.assertEqual(scala_version, '2.12')
    scala_jars = scala_platform['compiler_classpath']
    self.assertTrue(any('2.12' in jar_path for jar_path in scala_jars))

  def test_with_dependencies(self):
    result = self.execute_export_json('project_info:third')

    self.assertEqual(
      sorted(['java/project_info:java_lib']),
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
    self.assertEqual(sorted(['org.apache:apache-jar:12.12.2012']),
                     sorted(result['targets']['project_info:jvm_app']['libraries']))

  def test_jvm_target(self):
    self.maxDiff = None
    result = self.execute_export_json('project_info:jvm_target')
    jvm_target = result['targets']['project_info:jvm_target']
    jvm_target['libraries'] = sorted(jvm_target['libraries'])
    expected_jvm_target = {
      'scalac_args': [],
      'javac_args': [],
      'extra_jvm_options': [],
      'excludes': [],
      'globs': {'globs': ['project_info/this/is/a/source/Foo.scala',
                          'project_info/this/is/a/source/Bar.scala']},
      'libraries': sorted([
        'org.apache:apache-jar:12.12.2012',
        'org.scala-lang:scala-library:2.10.5'
      ]),
      'id': 'project_info.jvm_target',
      # 'is_code_gen': False,
      'targets': [],
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
      'platform': 'java8',
    }
    self.assertEqual(jvm_target, expected_jvm_target)

  def test_java_test(self):
    result = self.execute_export_json('project_info:java_test')
    self.assertEqual('TEST', result['targets']['project_info:java_test']['target_type'])
    # Note that the junit dep gets auto-injected via the JUnit subsystem.
    self.assertEqual(sorted([
                       'org.apache:apache-jar:12.12.2012',
                       'junit:junit:{}'.format(JUnit.LIBRARY_REV),
                       'project_info.test_resource',
                     ]),
                     sorted(result['targets']['project_info:java_test']['libraries']))

  def test_jvm_binary(self):
    result = self.execute_export_json('project_info:jvm_binary')
    self.assertEqual(sorted(['org.apache:apache-jar:12.12.2012']),
                     sorted(result['targets']['project_info:jvm_binary']['libraries']))

  def test_top_dependency(self):
    result = self.execute_export_json('project_info:top_dependency')
    self.assertEqual(sorted(['project_info.jvm_binary', 'org.apache:apache-jar:12.12.2012']),
                     sorted(result['targets']['project_info:top_dependency']['libraries']))
    self.assertEqual([], result['targets']['project_info:top_dependency']['targets'])

  def test_format_flag(self):
    self.set_options(formatted=False)
    result = self.execute_export('project_info:third')
    # confirms only one line of output, which is what -format should produce
    self.assertEqual(1, len(result))

  def test_target_types_with_resource_as_deps(self):
    result = self.execute_export_json('project_info:target_type')
    self.assertEqual('SOURCE',
                     result['targets']['project_info:target_type']['target_type'])
    self.assertIn('project_info.resource', result['targets']['project_info:target_type']['libraries'])
    self.assertTrue(result['libraries']['project_info.resource']['default'].endswith('.jar'))

  def test_target_types_with_resource_as_root(self):
    result = self.execute_export_json(*['project_info:target_type', 'project_info:resource'])
    self.assertEqual('SOURCE',
      result['targets']['project_info:target_type']['target_type'])
    self.assertEqual('RESOURCE', result['targets']['project_info:resource']['target_type'])
    self.assertEqual([], result['targets']['project_info:resource']['libraries'])
    roots = result['targets']['project_info:resource']['roots']
    self.assertEqual(1, len(roots))
    self.assertEqual(os.path.join(self.build_root, 'project_info'), roots[0]['source_root'])

  def test_target_platform(self):
    result = self.execute_export_json('project_info:target_type')
    self.assertEqual('java8',
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
        self.assertEqual(strict_home, export_json['preferred_jvm_distributions']['java9999']['strict'],
                         "strict home does not match")

        # Since it is non-strict, it can be either.
        self.assertIn(export_json['preferred_jvm_distributions']['java9999']['non_strict'],
                      [non_strict_home, strict_home],
                      "non-strict home does not match")

  def test_includes_zjars_in_dependencies(self):

    result = self.execute_export_json('project_info:scala_with_source_dep')
    self.assertIn(
      'project_info.jvm_target',
      result['libraries']
    )
    self.assertIn(
      'z.jar',
      result['libraries']['project_info.jvm_target']['default']
    )

  def test_dont_export_sources_by_default(self):

    result = self.execute_export_json('project_info:scala_with_source_dep')

    self.assertIn(
      'project_info.jvm_target',
      result['libraries']
    )

    self.assertNotIn(
      'sources',
      result['libraries']['project_info.jvm_target']
    )

  def test_export_sources_if_flag_passed(self):
    self.set_options(sources=True)
    result = self.execute_export_json('project_info:scala_with_source_dep')

    print(json.dumps(result))

    self.assertIn(
      'project_info.jvm_target',
      result['libraries']
    )
    self.assertIn(
      'sources',
      result['libraries']['project_info.jvm_target']
    )
    self.assertIn(
      '-sources.jar',
      result['libraries']['project_info.jvm_target']['sources']
    )

    sources_jar_of_dep = ZipFile(result['libraries']['project_info.jvm_target']['sources'])

    self.assertEqual(
      sorted(self.jvm_target_with_sources.sources_relative_to_source_root()),
      sorted(sources_jar_of_dep.namelist())
    )

  def test_includes_targets_between_roots(self):
    result = self.execute_export_json('project_info:scala_with_source_dep', 'project_info:jar_lib')
    self.assertIn(
      'project_info:jvm_target',
      result['targets'].keys()
    )

  def test_target_roots_dont_generate_libs(self):
    result = self.execute_export_json('project_info:scala_with_source_dep', 'project_info:jvm_target')
    self.assertNotIn(
      'project_info.scala_with_source_dep',
      result['targets']['project_info:scala_with_source_dep']['libraries']
    )
    self.assertNotIn(
      'project_info.jvm_target',
      result['targets']['project_info:scala_with_source_dep']['libraries']
    )
    self.assertNotIn(
      'project_info.scala_with_source_dep',
      result['libraries'].keys()
    )
    self.assertNotIn(
      'project_info.jvm_target',
      result['libraries'].keys()
    )

  def test_transitive_libs_only_added_if_dependency_is_not_modulizable(self):
    a_spec = self.linear_build_graph['a'].address.spec
    b_spec = self.linear_build_graph['b'].address.spec
    result_a = self.execute_export_json(a_spec)
    self.assertEquals(
      sorted([
        'project_info.b',
        'project_info.c',
        'project_info.d',
        'project_info.e',
        'org.scala-lang:scala-library:2.10.5',
      ]),
      sorted(result_a['targets'][a_spec]['libraries'])
    )
    result_ab = self.execute_export_json(a_spec, b_spec)
    self.assertEquals(
      sorted(['org.scala-lang:scala-library:2.10.5']),
      sorted(result_ab['targets'][a_spec]['libraries'])
    )
    self.assertIn(
      b_spec,
      result_ab['targets'][a_spec]['targets']
    )
    self.assertEquals(
      sorted([
        'project_info.c',
        'project_info.d',
        'project_info.e',
        'org.scala-lang:scala-library:2.10.5',
      ]),
      sorted(result_ab['targets'][b_spec]['libraries'])
    )

  def test_imports_3rdparty_jars_from_transitive_dependencies(self):
    spec = self.scala_with_source_dep.address.spec
    result = self.execute_export_json(spec)
    self.assertIn(
      'org.apache:apache-jar:12.12.2012',
      result['targets'][spec]['libraries']
    )
