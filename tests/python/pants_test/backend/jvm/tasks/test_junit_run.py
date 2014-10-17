# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import os
import subprocess
import sys
from textwrap import dedent

from pants.backend.core.targets.resources import Resources
from pants.backend.jvm.tasks.junit_run import JUnitRun
from pants.goal.products import MultipleRootedProducts
from pants.ivy.bootstrapper import Bootstrapper
from pants.java.distribution.distribution import Distribution
from pants.java.executor import SubprocessExecutor
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class JUnitRunnerTest(JvmToolTaskTestBase):
  """Tests for junit_run._JUnitRunner class"""

  @classmethod
  def task_type(cls):
    return JUnitRun

  def create_options(self, **kwargs):
    options = dict(junit_run_coverage=False,
                   junit_run_coverage_html_open=False,
                   junit_run_jvmargs=None,
                   junit_run_debug=False,
                   junit_run_tests=None,
                   junit_run_batch_size=sys.maxint,
                   junit_run_fail_fast=False,
                   junit_run_xmlreport=False,
                   junit_run_per_test_timer=False,
                   junit_run_default_parallel=False,
                   junit_run_parallel_threads=0,
                   junit_run_test_shard=None,
                   junit_run_arg=None,
                   junit_run_suppress_output=True,
                   junit_run_skip=False)
    options.update(**kwargs)
    return super(JUnitRunnerTest, self).create_options(**options)

  def test_junit_runner(self):

    # Create the temporary base test directory
    test_rel_path = 'tests/java/com/pants/foo'
    test_abs_path = os.path.join(self.build_root, test_rel_path)
    self.create_dir(test_rel_path)

    # Generate the temporary java test source code.
    test_java_file_rel_path = os.path.join(test_rel_path, 'FooTest.java')
    test_java_file_abs_path = os.path.join(self.build_root, test_java_file_rel_path)
    self.create_file(test_java_file_rel_path,
      dedent('''
        import org.junit.Test;
        import static org.junit.Assert.assertTrue;
        public class FooTest {
          @Test
          public void testFoo() {
            assertTrue(5 > 3);
          }
        }
      '''))

    # Invoke ivy to resolve classpath for junit.
    distribution = Distribution.cached(jdk=True)
    executor = SubprocessExecutor(distribution=distribution)
    classpath_file_abs_path = os.path.join(test_abs_path, 'junit.classpath')
    ivy = Bootstrapper.default_ivy(java_executor=executor)
    ivy.execute(args=['-cachepath', classpath_file_abs_path,
                      '-dependency', 'junit', 'junit-dep', '4.10'])
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

    # Also we need to add the FooTest.class's classpath to the exclusive_groups
    # products data mapping so JUnitRun will be able to add that into the final
    # classpath under which the junit will be executed.
    self.populate_exclusive_groups(
      context=context,
      classpaths=[test_abs_path],
      # This is a bit hacky. The issue in https://github.com/pantsbuild/pants/issues/508
      # is that normal resources specified in the BUILD targets are fine, but the
      # synthetic resources ones generated on the fly don't have exclusive_groups data
      # mapping entries thus later on in _JUnitRunner lookup it blows up. So we manually
      # exclude the synthetic resources target here to simulate that situation and ensure
      # the _JUnitRunner does filter out all the non-java-tests targets.
      target_predicate=lambda t: t != resources)

    # Finally execute the task.
    self.execute(context)


class EmmaTest(JvmToolTaskTestBase):
  """Tests for junit_run.Emma class"""
  # TODO(Jin Feng) to be implemented


class CoberturaTest(JvmToolTaskTestBase):
  """Tests for junit_run.Cobertura class"""
  # TODO(Jin Feng) to be implemented
