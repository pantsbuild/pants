# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
from textwrap import dedent

from mock import patch

from pants.backend.jvm.subsystems.junit import JUnit
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.tasks.junit_run import JUnitRun
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.resources import Resources
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_file_dump
from pants.util.timeout import TimeoutReached
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase
from pants_test.subsystem.subsystem_util import global_subsystem_instance, init_subsystem


class JUnitRunnerTest(JvmToolTaskTestBase):
  """Tests for junit_run._JUnitRunner class"""

  @classmethod
  def task_type(cls):
    return JUnitRun

  @property
  def alias_groups(self):
    return super(JUnitRunnerTest, self).alias_groups.merge(BuildFileAliases(
      targets={
        'junit_tests': JUnitTests,
        'python_tests': PythonTests,
      },
    ))

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

  def setUp(self):
    super(JUnitRunnerTest, self).setUp()
    init_subsystem(JUnit)

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

  def test_junit_runner_timeout_success(self):
    """When we set a timeout and don't force failure, succeed."""

    with patch('pants.task.testrunner_task_mixin.Timeout') as mock_timeout:
      self.set_options(timeout_default=1)
      self.set_options(timeouts=True)
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

      # Ensures that Timeout is instantiated with a 1 second timeout.
      args, kwargs = mock_timeout.call_args
      self.assertEqual(args, (1,))

  def test_junit_runner_timeout_fail(self):
    """When we set a timeout and force a failure, fail."""

    with patch('pants.task.testrunner_task_mixin.Timeout') as mock_timeout:
      mock_timeout().__exit__.side_effect = TimeoutReached(1)

      self.set_options(timeout_default=1)
      self.set_options(timeouts=True)
      with self.assertRaises(TaskError) as cm:
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

      self.assertEqual([t.name for t in cm.exception.failed_targets], ['foo_test'])

      # Ensures that Timeout is instantiated with a 1 second timeout.
      args, kwargs = mock_timeout.call_args
      self.assertEqual(args, (1,))

  def _execute_junit_runner(self, list_of_filename_content_tuples, create_some_resources=True, **kwargs):
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

    # Now directly invoking javac to compile the test java code into java class
    # so later we can inject the class into products mapping for JUnitRun to execute
    # the test on.
    javac = distribution.binary('javac')
    subprocess.check_call(
      [javac, '-d', test_classes_abs_path, '-cp', classpath] + test_java_file_abs_paths)

    # If a target_name is specified create a target with it, otherwise create a junit_tests target.
    if 'target_name' in kwargs:
      target = self.target(kwargs['target_name'])
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
    task = self.create_task(self.context(target_roots=[self.target('foo:hello')]))
    task.execute()

  def test_empty_sources(self):
    self.add_to_build_file('foo', dedent("""
        junit_tests(
          name='empty',
          sources=[],
        )
        """
    ))
    task = self.create_task(self.context(target_roots=[self.target('foo:empty')]))
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'must include a non-empty set of sources'):
      task.execute()

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
    self.create_task(context).execute()

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

  def test_junit_runner_extra_jvm_options(self):
    self.make_target(
      spec='foo:foo_test',
      target_type=JUnitTests,
      sources=['FooTest.java'],
      extra_jvm_options=['-Dexample.property=1'],
    )
    self._execute_junit_runner([('FooTest.java', dedent("""
        import org.junit.Test;
        import static org.junit.Assert.assertTrue;
        public class FooTest {
          @Test
          public void testFoo() {
            String exampleProperty = System.getProperty("example.property");
            assertTrue(exampleProperty != null && exampleProperty.equals("1"));
          }
        }
      """))], target_name='foo:foo_test')

  def test_junit_runner_multiple_extra_jvm_options(self):
    self.make_target(
      spec='foo:foo_test',
      target_type=JUnitTests,
      sources=['FooTest.java'],
      extra_jvm_options=['-Dexample.property1=1','-Dexample.property2=2'],
    )
    self._execute_junit_runner([('FooTest.java', dedent("""
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
      """))], target_name='foo:foo_test')

  def test_junit_runner_extra_env_vars(self):
    self.make_target(
      spec='foo:foo_test',
      target_type=JUnitTests,
      sources=['FooTest.java'],
      extra_env_vars={
        'HELLO': 27,
        'THERE': 32,
      },
    )

    self.make_target(
      spec='bar:bar_test',
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
      ], target_name='foo:foo_test')

    # Execute twice in a row to make sure the environment changes aren't sticky.
    self._execute_junit_runner([('FooTest.java', dedent("""
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
      """))], target_name='bar:bar_test', create_some_resources=False)

  def test_junit_runner_extra_env_vars_none(self):
    with environment_as(THIS_VARIABLE="12", THAT_VARIABLE="This is a variable."):
      self.make_target(
        spec='foo:foo_test',
        target_type=JUnitTests,
        sources=['FooTest.java'],
        extra_env_vars={
          'HELLO': None,
          'THERE': False,
          'THIS_VARIABLE': None
        },
      )

      self._execute_junit_runner([('FooTest.java', dedent("""
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
        """))], target_name='foo:foo_test')

  def test_junt_run_with_too_many_args(self):
    max_subprocess_args = 2
    num_of_classes = 5

    list_of_filename_content_tuples = []
    for n in range(num_of_classes):
      filename = 'FooTest{}.java'.format(n)
      content = dedent("""
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
      spec='foo:foo_test',
      target_type=JUnitTests,
      sources=[name for name, _ in list_of_filename_content_tuples],
    )
    self.set_options(max_subprocess_args=max_subprocess_args)

    self._execute_junit_runner(list_of_filename_content_tuples, target_name='foo:foo_test')
