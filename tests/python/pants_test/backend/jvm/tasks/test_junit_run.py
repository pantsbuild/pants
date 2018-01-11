# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager
from textwrap import dedent

from pants.backend.jvm.subsystems.junit import JUnit
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.tasks.coverage.cobertura import Cobertura
from pants.backend.jvm.tasks.coverage.engine import NoCoverage
from pants.backend.jvm.tasks.coverage.jacoco import Jacoco
from pants.backend.jvm.tasks.coverage.manager import CodeCoverage
from pants.backend.jvm.tasks.junit_run import JUnitRun
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.files import Files
from pants.build_graph.resources import Resources
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_file_dump, touch
from pants.util.process_handler import subprocess
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase
from pants_test.subsystem.subsystem_util import global_subsystem_instance, init_subsystem
from pants_test.tasks.task_test_base import ensure_cached


class JUnitRunnerTest(JvmToolTaskTestBase):

  @classmethod
  def task_type(cls):
    return JUnitRun

  @property
  def alias_groups(self):
    return super(JUnitRunnerTest, self).alias_groups.merge(BuildFileAliases(
      targets={
        'files': Files,
        'junit_tests': JUnitTests,
        'python_tests': PythonTests,
      },
    ))

  def setUp(self):
    super(JUnitRunnerTest, self).setUp()
    init_subsystem(JUnit)

  @ensure_cached(JUnitRun, expected_num_artifacts=1)
  def test_junit_runner_success(self):
    self._execute_junit_runner(
      [('FooTest.java', dedent("""
        import org.junit.Test;
        import static org.junit.Assert.assertTrue;
        public class FooTest {
          @Test
          public void testFoo() {
            assertTrue(5 > 3);
          }
        }
      """))]
    )

  @ensure_cached(JUnitRun, expected_num_artifacts=0)
  def test_junit_runner_failure(self):
    with self.assertRaises(TaskError) as cm:
      self._execute_junit_runner(
        [('FooTest.java', dedent("""
          import org.junit.Test;
          import static org.junit.Assert.assertTrue;
          public class FooTest {
            @Test
            public void testFoo() {
              assertTrue(5 < 3);
            }
          }
        """))]
      )

    self.assertEqual([t.name for t in cm.exception.failed_targets], ['foo_test'])

  @ensure_cached(JUnitRun, expected_num_artifacts=0)
  def test_junit_runner_error(self):
    with self.assertRaises(TaskError) as cm:
      self._execute_junit_runner(
        [('FooTest.java', dedent("""
          import org.junit.Test;
          public class FooTest {
            @Test
            public void testFoo() {
              throw new RuntimeException("test error");
            }
          }
        """))]
      )

    self.assertEqual([t.name for t in cm.exception.failed_targets], ['foo_test'])

  def _execute_junit_runner(self, list_of_filename_content_tuples, create_some_resources=True,
                            target_name=None):
    # Create the temporary base test directory
    test_rel_path = 'tests/java/org/pantsbuild/foo'
    test_abs_path = self.create_dir(test_rel_path)

    # Create the temporary classes directory under work dir
    test_classes_abs_path = self.create_workdir_dir(test_rel_path)

    test_java_file_abs_paths = []
    # Generate the temporary java test source code.
    for filename, content in list_of_filename_content_tuples:
      test_java_file_rel_path = os.path.join(test_rel_path, filename)
      test_java_file_abs_path = self.create_file(test_java_file_rel_path, content)
      test_java_file_abs_paths.append(test_java_file_abs_path)

    # Invoke ivy to resolve classpath for junit.
    classpath_file_abs_path = os.path.join(test_abs_path, 'junit.classpath')
    ivy_subsystem = global_subsystem_instance(IvySubsystem)
    distribution = DistributionLocator.cached(jdk=True)
    ivy = Bootstrapper(ivy_subsystem=ivy_subsystem).ivy()
    ivy.execute(args=['-cachepath', classpath_file_abs_path,
                      '-dependency', 'junit', 'junit-dep', '4.10'],
                executor=SubprocessExecutor(distribution=distribution))

    with open(classpath_file_abs_path) as fp:
      classpath = fp.read()

    # Now directly invoke javac to compile the test java code into classfiles that we can later
    # inject into a product mapping for JUnitRun to execute against.
    javac = distribution.binary('javac')
    subprocess.check_call(
      [javac, '-d', test_classes_abs_path, '-cp', classpath] + test_java_file_abs_paths)

    # If a target_name is specified create a target with it, otherwise create a junit_tests target.
    if target_name:
      target = self.target(target_name)
    else:
      target = self.create_library(test_rel_path, 'junit_tests', 'foo_test', ['FooTest.java'])

    target_roots = []
    if create_some_resources:
      # Create a synthetic resource target.
      target_roots.append(self.make_target('some_resources', Resources))
    target_roots.append(target)

    # Set the context with the two targets, one junit_tests target and
    # one synthetic resources target.
    # The synthetic resources target is to make sure we won't regress
    # in the future with bug like https://github.com/pantsbuild/pants/issues/508. Note
    # in that bug, the resources target must be the first one in the list.
    context = self.context(target_roots=target_roots)

    # Before we run the task, we need to inject the "runtime_classpath" with
    # the compiled test java classes that JUnitRun will know which test
    # classes to execute. In a normal run, this "runtime_classpath" will be
    # populated by java compilation step.
    self.populate_runtime_classpath(context=context, classpath=[test_classes_abs_path])

    # Finally execute the task.
    self.execute(context)

  @ensure_cached(JUnitRun, expected_num_artifacts=0)
  def test_junit_runner_raises_no_error_on_non_junit_target(self):
    """Run pants against a `python_tests` target, but set an option for the `test.junit` task. This
    should execute without error.
    """
    self.add_to_build_file('foo', dedent("""
        python_tests(
          name='hello',
          sources=['some_file.py'],
        )
        """
    ))
    self.set_options(test='#abc')
    self.execute(self.context(target_roots=[self.target('foo:hello')]))

  @ensure_cached(JUnitRun, expected_num_artifacts=0)
  def test_empty_sources(self):
    self.add_to_build_file('foo', dedent("""
        junit_tests(
          name='empty',
          sources=[],
        )
        """
    ))
    task = self.prepare_execute(self.context(target_roots=[self.target('foo:empty')]))
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'must include a non-empty set of sources'):
      task.execute()

  # We should skip the execution (and caching) phase when there are no test sources.
  @ensure_cached(JUnitRun, expected_num_artifacts=0)
  def test_allow_empty_sources(self):
    self.add_to_build_file('foo', dedent("""
        junit_tests(
          name='empty',
          sources=[],
        )
        """
    ))
    self.set_options(allow_empty_sources=True)
    context = self.context(target_roots=[self.target('foo:empty')])
    self.populate_runtime_classpath(context=context)
    self.execute(context)

  def test_request_classes_by_source(self):
    """`classes_by_source` is expensive to compute: confirm that it is only computed when needed."""

    # Class names (with and without a method name) should not trigger.
    self.assertFalse(JUnitRun.request_classes_by_source(['com.goo.ber']))
    self.assertFalse(JUnitRun.request_classes_by_source(['com.goo.ber#method']))

    # Existing files (with and without the method name) should trigger.
    srcfile = os.path.join(self.test_workdir, 'this.is.a.source.file.scala')
    safe_file_dump(srcfile, 'content!')
    self.assertTrue(JUnitRun.request_classes_by_source([srcfile]))
    self.assertTrue(JUnitRun.request_classes_by_source(['{}#method'.format(srcfile)]))

  @ensure_cached(JUnitRun, expected_num_artifacts=1)
  def test_junit_runner_extra_jvm_options(self):
    self.make_target(
      spec='tests/java/org/pantsbuild/foo:foo_test',
      target_type=JUnitTests,
      sources=['FooTest.java'],
      extra_jvm_options=['-Dexample.property=1'],
    )
    self._execute_junit_runner([('FooTest.java', dedent("""
        package org.pantsbuild.foo;
        import org.junit.Test;
        import static org.junit.Assert.assertTrue;
        public class FooTest {
          @Test
          public void testFoo() {
            String exampleProperty = System.getProperty("example.property");
            assertTrue(exampleProperty != null && exampleProperty.equals("1"));
          }
        }
      """))], target_name='tests/java/org/pantsbuild/foo:foo_test')

  @ensure_cached(JUnitRun, expected_num_artifacts=1)
  def test_junit_runner_multiple_extra_jvm_options(self):
    self.make_target(
      spec='tests/java/org/pantsbuild/foo:foo_test',
      target_type=JUnitTests,
      sources=['FooTest.java'],
      extra_jvm_options=['-Dexample.property1=1','-Dexample.property2=2'],
    )
    self._execute_junit_runner([('FooTest.java', dedent("""
        package org.pantsbuild.foo;
        import org.junit.Test;
        import static org.junit.Assert.assertTrue;
        public class FooTest {
          @Test
          public void testFoo() {
            String exampleProperty1 = System.getProperty("example.property1");
            assertTrue(exampleProperty1 != null && exampleProperty1.equals("1"));
            String exampleProperty2 = System.getProperty("example.property2");
            assertTrue(exampleProperty2 != null && exampleProperty2.equals("2"));
            String exampleProperty3 = System.getProperty("example.property3");
            assertTrue(exampleProperty3 == null);
          }
        }
      """))], target_name='tests/java/org/pantsbuild/foo:foo_test')

  # 2 runs with different targets (unique configurations), should cache twice.
  @ensure_cached(JUnitRun, expected_num_artifacts=2)
  def test_junit_runner_extra_env_vars(self):
    self.make_target(
      spec='tests/java/org/pantsbuild/foo:foo_test',
      target_type=JUnitTests,
      sources=['FooTest.java'],
      extra_env_vars={
        'HELLO': 27,
        'THERE': 32,
      },
    )

    self.make_target(
      spec='tests/java/org/pantsbuild/foo:bar_test',
      target_type=JUnitTests,
      sources=['FooTest.java'],
      extra_env_vars={
        'THE_ANSWER': 42,
        'HELLO': 12,
      },
    )

    self._execute_junit_runner(
      [
        ('FooTest.java', dedent("""
        package org.pantsbuild.foo;
        import org.junit.Test;
        import static org.junit.Assert.assertEquals;
        public class FooTest {
          @Test
          public void testFoo() {
            assertEquals("27", System.getenv().get("HELLO"));
            assertEquals("32", System.getenv().get("THERE"));
          }
        }
      """))
      ], target_name='tests/java/org/pantsbuild/foo:foo_test')

    # Execute twice in a row to make sure the environment changes aren't sticky.
    self._execute_junit_runner([('FooTest.java', dedent("""
        package org.pantsbuild.foo;
        import org.junit.Test;
        import static org.junit.Assert.assertEquals;
        import static org.junit.Assert.assertFalse;
        public class FooTest {
          @Test
          public void testFoo() {
            assertEquals("12", System.getenv().get("HELLO"));
            assertEquals("42", System.getenv().get("THE_ANSWER"));
            assertFalse(System.getenv().containsKey("THERE"));
          }
        }
      """))], target_name='tests/java/org/pantsbuild/foo:bar_test', create_some_resources=False)

  @ensure_cached(JUnitRun, expected_num_artifacts=1)
  def test_junit_runner_extra_env_vars_none(self):
    with environment_as(THIS_VARIABLE="12", THAT_VARIABLE="This is a variable."):
      self.make_target(
        spec='tests/java/org/pantsbuild/foo:foo_test',
        target_type=JUnitTests,
        sources=['FooTest.java'],
        extra_env_vars={
          'HELLO': None,
          'THERE': False,
          'THIS_VARIABLE': None
        },
      )

      self._execute_junit_runner([('FooTest.java', dedent("""
          package org.pantsbuild.foo;
          import org.junit.Test;
          import static org.junit.Assert.assertEquals;
          import static org.junit.Assert.assertFalse;
          public class FooTest {
            @Test
            public void testFoo() {
              assertEquals("False", System.getenv().get("THERE"));
              assertEquals("This is a variable.", System.getenv().get("THAT_VARIABLE"));
              assertFalse(System.getenv().containsKey("HELLO"));
              assertFalse(System.getenv().containsKey("THIS_VARIABLE"));
            }
          }
        """))], target_name='tests/java/org/pantsbuild/foo:foo_test')

  @ensure_cached(JUnitRun, expected_num_artifacts=1)
  def test_junt_run_with_too_many_args(self):
    max_subprocess_args = 2
    num_of_classes = 5

    list_of_filename_content_tuples = []
    for n in range(num_of_classes):
      filename = 'FooTest{}.java'.format(n)

      content = dedent("""
          package org.pantsbuild.foo;
          import org.junit.Test;
          import static org.junit.Assert.assertTrue;
          public class FooTest{}{{
          @Test
            public void testFoo() {{
              int x = 5;
            }}
          }}""".format(n))
      list_of_filename_content_tuples.append((filename, content))

    self.make_target(
      spec='tests/java/org/pantsbuild/foo:foo_test',
      target_type=JUnitTests,
      sources=[name for name, _ in list_of_filename_content_tuples],
    )
    self.set_options(max_subprocess_args=max_subprocess_args)

    self._execute_junit_runner(list_of_filename_content_tuples,
                               target_name='tests/java/org/pantsbuild/foo:foo_test')

  @ensure_cached(JUnitRun, expected_num_artifacts=1)
  def test_junit_run_chroot(self):
    self.create_files('config/org/pantsbuild/foo', ['sentinel', 'another'])
    files = self.make_target(
      spec='config/org/pantsbuild/foo:sentinel',
      target_type=Files,
      sources=['sentinel']
    )
    self.make_target(
      spec='tests/java/org/pantsbuild/foo:foo_test',
      target_type=JUnitTests,
      sources=['FooTest.java'],
      dependencies=[files]
    )
    content = dedent("""
        package org.pantsbuild.foo;
        import java.io.File;
        import org.junit.Test;
        import static org.junit.Assert.assertFalse;
        import static org.junit.Assert.assertTrue;
        public class FooTest {
          @Test
          public void testFoo() {
            assertTrue(new File("config/org/pantsbuild/foo/sentinel").exists());
            assertFalse(new File("config/org/pantsbuild/foo/another").exists());
          }
        }
      """)
    self.set_options(chroot=True)
    self._execute_junit_runner([('FooTest.java', content)],
                               target_name='tests/java/org/pantsbuild/foo:foo_test')

  @ensure_cached(JUnitRun, expected_num_artifacts=0)
  def test_junit_run_chroot_cwd_mutex(self):
    with temporary_dir() as chroot:
      self.set_options(chroot=True, cwd=chroot)
      with self.assertRaises(JUnitRun.OptionError):
        self.execute(self.context())

  @ensure_cached(JUnitRun, expected_num_artifacts=1)
  def test_junit_run_target_cwd_trumps_chroot(self):
    with temporary_dir() as target_cwd:
      self.create_files('config/org/pantsbuild/foo', ['files_dep_sentinel'])
      files = self.make_target(
        spec='config/org/pantsbuild/foo:sentinel',
        target_type=Files,
        sources=['files_dep_sentinel']
      )
      self.make_target(
        spec='tests/java/org/pantsbuild/foo:foo_test',
        target_type=JUnitTests,
        sources=['FooTest.java'],
        dependencies=[files],
        cwd=target_cwd
      )
      content = dedent("""
        package org.pantsbuild.foo;
        import java.io.File;
        import org.junit.Test;
        import static org.junit.Assert.assertFalse;
        import static org.junit.Assert.assertTrue;
        public class FooTest {{
          @Test
          public void testFoo() {{
            assertTrue(new File("target_cwd_sentinel").exists());

            // We declare a Files dependency on this file, but since we run in a CWD not in a
            // chroot and not in the build root, we can't find it at the expected relative path.
            assertFalse(new File("config/org/pantsbuild/foo/files_dep_sentinel").exists());

            // As a sanity check, it is at the expected absolute path though.
            File buildRoot = new File("{}");
            assertTrue(new File(buildRoot,
                                "config/org/pantsbuild/foo/files_dep_sentinel").exists());
          }}
        }}
      """.format(self.build_root))
      touch(os.path.join(target_cwd, 'target_cwd_sentinel'))
      self.set_options(chroot=True)
      self._execute_junit_runner([('FooTest.java', content)],
                                 target_name='tests/java/org/pantsbuild/foo:foo_test')

  @ensure_cached(JUnitRun, expected_num_artifacts=1)
  def test_junit_run_target_cwd_trumps_cwd_option(self):
    with temporary_dir() as target_cwd:
      self.make_target(
        spec='tests/java/org/pantsbuild/foo:foo_test',
        target_type=JUnitTests,
        sources=['FooTest.java'],
        cwd=target_cwd
      )
      content = dedent("""
        package org.pantsbuild.foo;
        import java.io.File;
        import org.junit.Test;
        import static org.junit.Assert.assertFalse;
        import static org.junit.Assert.assertTrue;
        public class FooTest {
          @Test
          public void testFoo() {
            assertTrue(new File("target_cwd_sentinel").exists());
            assertFalse(new File("option_cwd_sentinel").exists());
          }
        }
      """)
      touch(os.path.join(target_cwd, 'target_cwd_sentinel'))
      with temporary_dir() as option_cwd:
        touch(os.path.join(option_cwd, 'option_cwd_sentinel'))
        self.set_options(cwd=option_cwd)
        self._execute_junit_runner([('FooTest.java', content)],
                                   target_name='tests/java/org/pantsbuild/foo:foo_test')

  def test_junit_run_with_coverage_caching(self):
    source_under_test_content = dedent("""
      package org.pantsbuild.foo;
      class Foo {
        static String foo() {
          return "foo";
        }
        static String bar() {
          return "bar";
        }
      }
    """)
    source_under_test = self.make_target(spec='tests/java/org/pantsbuild/foo',
                                         target_type=JavaLibrary,
                                         sources=['Foo.java'])

    test_content = dedent("""
      package org.pantsbuild.foo;
      import org.pantsbuild.foo.Foo;
      import org.junit.Test;
      import static org.junit.Assert.assertEquals;
      public class FooTest {
        @Test
        public void testFoo() {
          assertEquals("foo", Foo.foo());
        }
      }
    """)
    self.make_target(spec='tests/java/org/pantsbuild/foo:foo_test',
                     target_type=JUnitTests,
                     sources=['FooTest.java'],
                     dependencies=[source_under_test])

    self.set_options(coverage=True)

    with self.cache_check(expected_num_artifacts=1):
      self._execute_junit_runner([('Foo.java', source_under_test_content),
                                  ('FooTest.java', test_content)],
                                 target_name='tests/java/org/pantsbuild/foo:foo_test')

    # Now re-execute with a partial invalidation of the input targets. Since coverage is enabled,
    # that input set is {tests/java/org/pantsbuild/foo, tests/java/org/pantsbuild/foo:bar_test}
    # with only tests/java/org/pantsbuild/foo:bar_test invalidated. Even though the invalidation is
    # partial over all input targets, it is total over all the test targets in the input and so the
    # successful result run is eligible for caching.
    test_content_edited = dedent("""
      package org.pantsbuild.foo;
      import org.pantsbuild.foo.Foo;
      import org.junit.Test;
      import static org.junit.Assert.assertEquals;
      public class FooTest {
        @Test
        public void testFoo() {
          assertEquals("bar", Foo.bar());
        }
      }
    """)
    self.make_target(spec='tests/java/org/pantsbuild/foo:bar_test',
                     target_type=JUnitTests,
                     sources=['FooTest.java'],
                     dependencies=[source_under_test])

    with self.cache_check(expected_num_artifacts=1):
      self._execute_junit_runner([('Foo.java', source_under_test_content),
                                  ('FooTest.java', test_content_edited)],
                                 target_name='tests/java/org/pantsbuild/foo:bar_test',
                                 create_some_resources=False)

  @contextmanager
  def _coverage_engine(self):
    junit_run = self.prepare_execute(self.context())
    with temporary_dir() as output_dir:
      code_coverage = CodeCoverage.global_instance()
      yield code_coverage.get_coverage_engine(task=junit_run,
                                              output_dir=output_dir,
                                              all_targets=[],
                                              execute_java=junit_run.execute_java_for_coverage)

  def _assert_coverage_engine(self, expected_engine_type):
    with self._coverage_engine() as engine:
      self.assertIsInstance(engine, expected_engine_type)

  def test_coverage_default_off(self):
    self._assert_coverage_engine(NoCoverage)

  def test_coverage_explicit_on(self):
    self.set_options(coverage=True)
    self._assert_coverage_engine(Cobertura)

  def test_coverage_open_implicit_on(self):
    self.set_options(coverage_open=True)
    self._assert_coverage_engine(Cobertura)

  def test_coverage_processor_implicit_on(self):
    self.set_options(coverage_processor='jacoco')
    self._assert_coverage_engine(Jacoco)

  def test_coverage_processor_invalid(self):
    self.set_options(coverage_processor='bob')
    with self.assertRaises(CodeCoverage.InvalidCoverageEngine):
      with self._coverage_engine():
        self.fail("We should never get here.")
