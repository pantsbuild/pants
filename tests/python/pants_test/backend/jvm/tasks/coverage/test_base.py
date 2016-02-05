# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.coverage.base import Coverage, CoverageTaskSettings
from pants_test.base_test import BaseTest


class attrdict(dict):
  """Allows entries in the dictionary to be accessed like a property, in order to spoof options.

  :API: public
  """

  def __getattr__(self, key):
    if self.has_key(key):
      return self[key]
    return None


class fake_log(object):
  """
  :API: public
  """

  def debug(self, string):
    """
    :API: public
    """
    return


class TestCoverageEngine(Coverage):
  """
  :API: public
  """

  def __init__(self, settings):
    self.copy2_calls = defaultdict(list)
    self.copytree_calls = defaultdict(list)
    self.safe_makedir_calls = []

    super(TestCoverageEngine, self).__init__(
        settings,
        copy2=lambda frm, to: self.copy2_calls[frm].append(to),
        copytree=lambda frm, to: self.copytree_calls[frm].append(to),
        is_file=lambda file_name: file_name.endswith('.jar'),
        safe_md=self.safe_md)

  def safe_md(self, dir, clean):
    """
    :API: public
    """
    assert clean == True
    self.safe_makedir_calls += dir

  def instrument(self, targets, tests, compute_junit_classpath, execute_java_for_targets):
    pass

  def report(self, targets, tests, execute_java_for_targets, tests_failed_exception):
    pass

  def classpath_prepend(self):
    pass

  def classpath_append(self):
    pass

  def extra_jvm_options(self):
    pass


class TestBase(BaseTest):
  """
  :API: public
  """

  def setUp(self):
    """
    :API: public
    """
    super(TestBase, self).setUp()

    self.pants_workdir = "workdir"
    self.conf = "default"

    self.jar_lib = self.make_target(spec='3rdparty/jvm/org/example:foo',
                                    target_type=JarLibrary,
                                    jars=[JarDependency(org='org.example', name='foo', rev='1.0.0'),
                                          JarDependency(org='org.pantsbuild', name='bar',
                                                        rev='2.0.0', ext='zip')])

    self.binary_target = self.make_target(spec='//foo:foo-binary',
                                          target_type=JvmBinary,
                                          source='Foo.java',
                                          dependencies=[self.jar_lib])

    self.app_target = self.make_target(spec='//foo:foo-app',
                                       target_type=JvmApp,
                                       basename='FooApp',
                                       dependencies=[self.binary_target])

    self.java_target = self.make_target(spec='//foo:foo-java',
                                        target_type=JavaLibrary)

    self.annotation_target = self.make_target(spec='//foo:foo-anno',
                                              target_type=AnnotationProcessor)

  def _add_for_target(self, products, target, path):
    products.add_for_target(target, [(self.conf, self.pants_workdir + path)])

  def _assert_calls(self, call_collection, frm, to):
    calls_for_target = call_collection[self.pants_workdir + frm]
    self.assertEquals(len(calls_for_target), 1, "Should be 1 call for the_target's path.")
    self.assertEquals(calls_for_target[0], self.pants_workdir + to, "Should copy from/to correct paths.")

  def _assert_target_copy(self, coverage, frm, to):
    self._assert_calls(coverage.copy2_calls, frm, to)

  def _assert_target_copytree(self, coverage, frm, to):
    self._assert_calls(coverage.copytree_calls, frm, to)

  def test_skips_non_coverage_targets(self):
    """
    :API: public
    """
    options = attrdict(coverage=True, coverage_jvm_options=[])

    settings = CoverageTaskSettings(options, None, self.pants_workdir, None, None, fake_log())
    coverage = TestCoverageEngine(settings)

    classpath_products = ClasspathProducts(self.pants_workdir)
    self._add_for_target(classpath_products, self.jar_lib, '/jar/lib/classpath')
    self._add_for_target(classpath_products, self.binary_target, '/binary/target/classpath')
    self._add_for_target(classpath_products, self.app_target, '/app/target/classpath')
    self._add_for_target(classpath_products, self.java_target, '/java/target/classpath.jar')

    coverage.initialize_instrument_classpath(
      [self.jar_lib, self.binary_target, self.app_target, self.java_target],
      classpath_products)

    self.assertEquals(len(coverage.copy2_calls), 1,
                      "Should only be 1 call for the single java_library target.")
    self._assert_target_copy(coverage, '/java/target/classpath.jar', '/coverage/classes/foo.foo-java/0')
    self.assertEquals(len(coverage.copytree_calls), 0,
                      "Should be no copytree calls when targets are not coverage targets.")

  def test_target_with_multiple_path_entries(self):
    """
    :API: public
    """
    options = attrdict(coverage=True, coverage_jvm_options=[])

    settings = CoverageTaskSettings(options, None, self.pants_workdir, None, None, fake_log())
    coverage = TestCoverageEngine(settings)

    classpath_products = ClasspathProducts(self.pants_workdir)
    self._add_for_target(classpath_products, self.java_target, '/java/target/first.jar')
    self._add_for_target(classpath_products, self.java_target, '/java/target/second.jar')
    self._add_for_target(classpath_products, self.java_target, '/java/target/third.jar')

    coverage.initialize_instrument_classpath([self.java_target], classpath_products)

    self.assertEquals(len(coverage.copy2_calls), 3,
                      "Should be 3 call for the single java_library target.")
    self._assert_target_copy(coverage, '/java/target/first.jar', '/coverage/classes/foo.foo-java/0')
    self._assert_target_copy(coverage, '/java/target/second.jar', '/coverage/classes/foo.foo-java/1')
    self._assert_target_copy(coverage, '/java/target/third.jar', '/coverage/classes/foo.foo-java/2')

    self.assertEquals(len(coverage.copytree_calls), 0,
                      "Should be no copytree calls when targets are not coverage targets.")

  def test_target_annotation_processor(self):
    """
    :API: public
    """
    options = attrdict(coverage=True, coverage_jvm_options=[])

    settings = CoverageTaskSettings(options, None, self.pants_workdir, None, None, fake_log())
    coverage = TestCoverageEngine(settings)

    classpath_products = ClasspathProducts(self.pants_workdir)
    self._add_for_target(classpath_products, self.annotation_target, '/anno/target/dir')

    coverage.initialize_instrument_classpath([self.annotation_target], classpath_products)

    self.assertEquals(len(coverage.copy2_calls), 0, "Should be 0 call for the single annotation target.")
    self._assert_target_copytree(coverage, '/anno/target/dir', '/coverage/classes/foo.foo-anno/0')
