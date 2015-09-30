# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
from collections import defaultdict
from textwrap import dedent

from pants.backend.core.targets.resources import Resources
from pants.backend.jvm.targets.java_tests import JavaTests
from pants.backend.jvm.tasks.junit_run import JUnitRun
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.products import MultipleRootedProducts
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase
from pants_test.subsystem.subsystem_util import subsystem_instance


class JUnitRunnerTest(JvmToolTaskTestBase):
  """Tests for junit_run._JUnitRunner class"""

  @classmethod
  def task_type(cls):
    return JUnitRun

  @property
  def alias_groups(self):
    return super(JUnitRunnerTest, self).alias_groups.merge(BuildFileAliases(
      targets={
        'java_tests': JavaTests,
        'python_tests': PythonTests,
      },
    ))

  def test_junit_runner_success(self):
    self.execute_junit_runner(
      dedent("""
        import org.junit.Test;
        import static org.junit.Assert.assertTrue;
        public class FooTest {
          @Test
          public void testFoo() {
            assertTrue(5 > 3);
          }
        }
      """)
    )

  def test_junit_runner_failure(self):
    with self.assertRaises(TaskError) as cm:
      self.execute_junit_runner(
        dedent("""
          import org.junit.Test;
          import static org.junit.Assert.assertTrue;
          public class FooTest {
            @Test
            public void testFoo() {
              assertTrue(5 < 3);
            }
          }
        """)
      )

    self.assertEqual([t.name for t in cm.exception.failed_targets], ['foo_test'])

  def test_junit_runner_error(self):
    with self.assertRaises(TaskError) as cm:
      self.execute_junit_runner(
        dedent("""
          import org.junit.Test;
          public class FooTest {
            @Test
            public void testFoo() {
              throw new RuntimeException("test error");
            }
          }
        """)
      )

    self.assertEqual([t.name for t in cm.exception.failed_targets], ['foo_test'])

  def execute_junit_runner(self, content):

    # Create the temporary base test directory
    test_rel_path = 'tests/java/org/pantsbuild/foo'
    test_abs_path = os.path.join(self.build_root, test_rel_path)
    self.create_dir(test_rel_path)

    # Generate the temporary java test source code.
    test_java_file_rel_path = os.path.join(test_rel_path, 'FooTest.java')
    test_java_file_abs_path = os.path.join(self.build_root, test_java_file_rel_path)
    self.create_file(test_java_file_rel_path, content)

    # Invoke ivy to resolve classpath for junit.
    classpath_file_abs_path = os.path.join(test_abs_path, 'junit.classpath')
    with subsystem_instance(IvySubsystem) as ivy_subsystem:
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
      [javac, '-d', test_abs_path, '-cp', classpath, test_java_file_abs_path])

    # Create a java_tests target and a synthetic resource target.
    java_tests = self.create_library(test_rel_path, 'java_tests', 'foo_test', ['FooTest.java'])
    resources = self.make_target('some_resources', Resources)

    # Set the context with the two targets, one java_tests target and
    # one synthetic resources target.
    # The synthetic resources target is to make sure we won't regress
    # in the future with bug like https://github.com/pantsbuild/pants/issues/508. Note
    # in that bug, the resources target must be the first one in the list.
    context = self.context(target_roots=[resources, java_tests])

    # Before we run the task, we need to inject the "classes_by_target" with
    # the compiled test java classes that JUnitRun will know which test
    # classes to execute. In a normal run, this "classes_by_target" will be
    # populated by java compiling step.
    class_products = context.products.get_data(
      'classes_by_target', lambda: defaultdict(MultipleRootedProducts))
    java_tests_products = MultipleRootedProducts()
    java_tests_products.add_rel_paths(test_abs_path, ['FooTest.class'])
    class_products[java_tests] = java_tests_products

    # Also we need to add the FooTest.class's classpath to the compile_classpath
    # products data mapping so JUnitRun will be able to add that into the final
    # classpath under which the junit will be executed.
    self.populate_compile_classpath(context=context, classpath=[test_abs_path])

    # Finally execute the task.
    self.execute(context)

  def test_junit_runner_raises_no_error_on_non_junit_target(self):
    """Run pants against a `python_tests` target, but set an option for the `test.junit` task. This
    should execute without error.
    """
    self.add_to_build_file('foo', dedent('''
        python_tests(
          name='hello',
          sources=['some_file.py'],
        )
        '''
    ))
    self.set_options(test='#abc')
    task = self.create_task(self.context(target_roots=[self.target('foo:hello')]))
    task.execute()

  def test_empty_sources(self):
    self.add_to_build_file('foo', dedent('''
        java_tests(
          name='empty',
          sources=[],
        )
        '''
    ))
    task = self.create_task(self.context(target_roots=[self.target('foo:empty')]))
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'must include a non-empty set of sources'):
      task.execute()
