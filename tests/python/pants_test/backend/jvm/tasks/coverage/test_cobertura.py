# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.coverage.cobertura import Cobertura
from pants.backend.jvm.tasks.coverage.manager import CodeCoverageSettings
from pants.java.jar.jar_dependency import JarDependency
from pants_test.base_test import BaseTest


class attrdict(dict):
  """Allows entries in the dictionary to be accessed like a property, in order to spoof options.

  :API: public
  """

  def __getattr__(self, key):
    return self.get(key)


class fake_log(object):
  """
  :API: public
  """

  def debug(self, string):
    """
    :API: public
    """
    pass

  def warn(self, string):
    """
    :API: public
    """
    pass


class MockSystemCalls(object):
  """
  :API: public
  """

  def __init__(self):
    self.copy2_calls = defaultdict(list)
    self.copytree_calls = defaultdict(list)
    self.safe_makedir_calls = []

  def safe_md(self, dir, clean):
    """
    :API: public
    """
    assert clean is True
    self.safe_makedir_calls.append(dir)


class TestCobertura(BaseTest):
  """
  :API: public
  """

  def get_settings(self, options, workdir, log, syscalls):
    return CodeCoverageSettings(
      options,
      None,
      self.pants_workdir,
      None,
      None,
      fake_log(),
      copy2=lambda frm, to: syscalls.copy2_calls[frm].append(to),
      copytree=lambda frm, to: syscalls.copytree_calls[frm].append(to),
      is_file=lambda file_name: file_name.endswith('.jar'),
      safe_md=syscalls.safe_md)

  def setUp(self):
    """
    :API: public
    """
    super(TestCobertura, self).setUp()

    self.pants_workdir = 'workdir'
    self.conf = 'default'
    self.factory = Cobertura.Factory("test_scope", [])

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
                                        target_type=JavaLibrary,
                                        sources=[])

    self.annotation_target = self.make_target(spec='//foo:foo-anno',
                                              target_type=AnnotationProcessor)

  def _add_for_target(self, products, target, path):
    products.add_for_target(target, [(self.conf, self.pants_workdir + path)])

  def _assert_calls(self, call_collection, frm, to):
    calls_for_target = call_collection[self.pants_workdir + frm]
    self.assertEquals(len(calls_for_target), 1, "Should be 1 call for the_target's path.")
    self.assertEquals(calls_for_target[0], self.pants_workdir + to,
                      'Should copy from/to correct paths.')

  def _assert_target_copy(self, coverage, frm, to):
    self._assert_calls(coverage.copy2_calls, frm, to)

  def _assert_target_copytree(self, coverage, frm, to):
    self._assert_calls(coverage.copytree_calls, frm, to)

  def test_skips_non_coverage_targets(self):
    """
    :API: public
    """
    options = attrdict(coverage=True, coverage_jvm_options=[])

    syscalls = MockSystemCalls()
    settings = self.get_settings(options, self.pants_workdir, fake_log(), syscalls)

    classpath_products = ClasspathProducts(self.pants_workdir)
    self._add_for_target(classpath_products, self.jar_lib, '/jar/lib/classpath')
    self._add_for_target(classpath_products, self.binary_target, '/binary/target/classpath')
    self._add_for_target(classpath_products, self.app_target, '/app/target/classpath')
    self._add_for_target(classpath_products, self.java_target, '/java/target/classpath.jar')

    Cobertura.initialize_instrument_classpath(
      settings,
      [self.jar_lib, self.binary_target, self.app_target, self.java_target],
      classpath_products)

    self.assertEquals(len(syscalls.copy2_calls), 1,
                      'Should only be 1 call for the single java_library target.')
    self._assert_target_copy(syscalls, '/java/target/classpath.jar',
                             '/coverage/classes/foo.foo-java/0')
    self.assertEquals(len(syscalls.copytree_calls), 0,
                      'Should be no copytree calls when targets are not coverage targets.')

  def test_target_with_multiple_path_entries(self):
    """
    :API: public
    """
    options = attrdict(coverage=True, coverage_jvm_options=[])

    syscalls = MockSystemCalls()
    settings = self.get_settings(options, self.pants_workdir, fake_log(), syscalls)

    classpath_products = ClasspathProducts(self.pants_workdir)
    self._add_for_target(classpath_products, self.java_target, '/java/target/first.jar')
    self._add_for_target(classpath_products, self.java_target, '/java/target/second.jar')
    self._add_for_target(classpath_products, self.java_target, '/java/target/third.jar')

    Cobertura.initialize_instrument_classpath(settings, [self.java_target], classpath_products)

    self.assertEquals(len(syscalls.copy2_calls), 3,
                      'Should be 3 call for the single java_library target.')
    self._assert_target_copy(syscalls, '/java/target/first.jar', '/coverage/classes/foo.foo-java/0')
    self._assert_target_copy(syscalls, '/java/target/second.jar',
                             '/coverage/classes/foo.foo-java/1')
    self._assert_target_copy(syscalls, '/java/target/third.jar',
                             '/coverage/classes/foo.foo-java/2')

    self.assertEquals(len(syscalls.copytree_calls), 0,
                      'Should be no copytree calls when targets are not coverage targets.')

  def test_target_annotation_processor(self):
    """
    :API: public
    """
    options = attrdict(coverage=True, coverage_jvm_options=[])

    syscalls = MockSystemCalls()
    settings = self.get_settings(options, self.pants_workdir, fake_log(), syscalls)

    classpath_products = ClasspathProducts(self.pants_workdir)
    self._add_for_target(classpath_products, self.annotation_target, '/anno/target/dir')

    Cobertura.initialize_instrument_classpath(settings, [self.annotation_target], classpath_products)

    self.assertEquals(len(syscalls.copy2_calls), 0,
                      'Should be 0 call for the single annotation target.')
    self._assert_target_copytree(syscalls, '/anno/target/dir', '/coverage/classes/foo.foo-anno/0')

  def _get_fake_execute_java(self):
    def _fake_execute_java(classpath, main, jvm_options, args, workunit_factory, workunit_name):
      # at some point we could add assertions here for expected paramerter values
      pass
    return _fake_execute_java

  def test_coverage_forced(self):
    """
    :API: public
    """
    options = attrdict(coverage=True, coverage_force=True, coverage_jvm_options=[])

    syscalls = MockSystemCalls()
    settings = self.get_settings(options, self.pants_workdir, fake_log(), syscalls)
    cobertura = self.factory.create(settings, [self.binary_target], self._get_fake_execute_java())

    self.assertEquals(cobertura.should_report(), False, 'Without instrumentation step, there should be nothing to instrument or report')

    # simulate an instrument step with results
    cobertura._nothing_to_instrument = False

    self.assertEquals(cobertura.should_report(), True, 'Should do reporting when there is something to instrument')

    exception = Exception("uh oh, test failed")

    self.assertEquals(cobertura.should_report(exception), True, 'We\'ve forced coverage, so should report.')

    no_force_options = attrdict(coverage=True, coverage_force=False, coverage_jvm_options=[])
    no_force_settings = self.get_settings(no_force_options, self.pants_workdir, fake_log(), syscalls)
    no_force_cobertura = self.factory.create(no_force_settings, [self.binary_target], self._get_fake_execute_java())

    no_force_cobertura._nothing_to_instrument = False
    self.assertEquals(no_force_cobertura.should_report(exception), False, 'Don\'t report after a failure if coverage isn\'t forced.')
