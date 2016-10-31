# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.engine import LocalSerialEngine
from pants.engine.nodes import Return, Throw
from pants.engine.selectors import Select, SelectVariant
from pants.engine.subsystem.native import Native
from pants.util.contextutil import temporary_dir
from pants_test.engine.examples.planners import (ApacheThriftJavaConfiguration, Classpath, GenGoal,
                                                 Jar, JavaSources, ThriftSources,
                                                 setup_json_scheduler)
from pants_test.subsystem.subsystem_util import subsystem_instance


walk = "TODO: Should port tests that attempt to inspect graph internals to the native code."


class SchedulerTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.spec_parser = CmdLineSpecParser(build_root)
    with subsystem_instance(Native.Factory) as native_factory:
      self.scheduler = setup_json_scheduler(build_root, native_factory.create())
    self.pg = self.scheduler.product_graph
    self.engine = LocalSerialEngine(self.scheduler)

    self.guava = Address.parse('3rdparty/jvm:guava')
    self.thrift = Address.parse('src/thrift/codegen/simple')
    self.java = Address.parse('src/java/codegen/simple')
    self.java_simple = Address.parse('src/java/simple')
    self.java_multi = Address.parse('src/java/multiple_classpath_entries')
    self.no_variant_thrift = Address.parse('src/java/codegen/selector:conflict')
    self.unconfigured_thrift = Address.parse('src/thrift/codegen/unconfigured')
    self.resources = Address.parse('src/resources/simple')
    self.consumes_resources = Address.parse('src/java/consumes_resources')
    self.consumes_managed_thirdparty = Address.parse('src/java/managed_thirdparty')
    self.managed_guava = Address.parse('3rdparty/jvm/managed:guava')
    self.managed_hadoop = Address.parse('3rdparty/jvm/managed:hadoop-common')
    self.managed_resolve_latest = Address.parse('3rdparty/jvm/managed:latest-hadoop')
    self.inferred_deps = Address.parse('src/scala/inferred_deps')

  def assert_select_for_subjects(self, walk, selector, subjects, variants=None):
    raise ValueError(walk)

  def build(self, build_request):
    """Execute the given request and return roots as a list of ((subject, product), value) tuples."""
    result = self.engine.execute(build_request)
    self.assertIsNone(result.error)
    return self.scheduler.root_entries(build_request).items()

  def request(self, goals, *addresses):
    return self.request_specs(goals, *[self.spec_parser.parse_spec(str(a)) for a in addresses])

  def request_specs(self, goals, *specs):
    return self.scheduler.build_request(goals=goals, subjects=specs)

  def assert_resolve_only(self, goals, root_specs, jars):
    build_request = self.request(goals, *root_specs)
    root, = self.build(build_request)

    # Expect a SelectNode for each of the Jar/Classpath.
    self.assert_select_for_subjects(walk, Select(Jar), jars)
    self.assert_select_for_subjects(walk, Select(Classpath), jars)

  def assert_root(self, root, subject, product_type, return_value):
    """Asserts that the given root has the given result."""
    self.assertEquals((subject, product_type), root[0])
    self.assertEquals(Return(return_value), root[1])

  def assert_root_failed(self, root, subject, product_type, msg_str):
    """Asserts that the root was a Throw result containing the given msg string."""
    self.assertEquals((subject, product_type), root[0])
    self.assertEquals(Throw, root[1])
    self.assertIn(msg_str, str(root[1].exc))

  def test_type_error_on_unexpected_subject_type(self):
    with self.assertRaises(TypeError) as cm:
      self.scheduler.build_request(goals={}, subjects=['string'])
    self.assertEquals("Unsupported root subject type: <type 'unicode'> for u'string'",
                      str(cm.exception))

  def test_resolve(self):
    self.assert_resolve_only(goals=['resolve'],
                             root_specs=['3rdparty/jvm:guava'],
                             jars=[self.guava])

  def test_compile_only_3rdparty(self):
    self.assert_resolve_only(goals=['compile'],
                             root_specs=['3rdparty/jvm:guava'],
                             jars=[self.guava])

  def test_gen_noop(self):
    # TODO(John Sirois): Ask around - is this OK?
    # This is different than today.  There is a gen'able target reachable from the java target, but
    # the scheduler 'pull-seeding' has ApacheThriftPlanner stopping short since the subject it's
    # handed is not thrift.
    build_request = self.request(['gen'], self.java)
    root, = self.build(build_request)

    self.assert_select_for_subjects(walk, Select(JavaSources, optional=True), [self.java])

  def test_gen(self):
    build_request = self.request(['gen'], self.thrift)
    root, = self.build(build_request)

    # Root: expect the synthetic GenGoal product.
    self.assert_root(root, self.thrift, GenGoal,
                     GenGoal("non-empty input to satisfy the Goal constructor"))

    variants = {'thrift': 'apache_java'}
    # Expect ThriftSources to have been selected.
    self.assert_select_for_subjects(walk, Select(ThriftSources), [self.thrift], variants=variants)
    # Expect an ApacheThriftJavaConfiguration to have been used via the default Variants.
    self.assert_select_for_subjects(walk, SelectVariant(ApacheThriftJavaConfiguration,
                                                        variant_key='thrift'),
                                    [self.thrift],
                                    variants=variants)

  def test_codegen_simple(self):
    build_request = self.request(['compile'], self.java)
    root, = self.build(build_request)

    # The subgraph below 'src/thrift/codegen/simple' will be affected by its default variants.
    subjects = [self.guava, self.java, self.thrift]
    variant_subjects = [
        Jar(org='org.apache.thrift', name='libthrift', rev='0.9.2', type_alias='jar'),
        Jar(org='commons-lang', name='commons-lang', rev='2.5', type_alias='jar'),
        Address.parse('src/thrift:slf4j-api')]

    # Root: expect a DependenciesNode depending on a SelectNode with compilation via javac.
    self.assert_root(root, self.java, Classpath, Classpath(creator='javac'))

    # Confirm that exactly the expected subjects got Classpaths.
    self.assert_select_for_subjects(walk, Select(Classpath), subjects)
    self.assert_select_for_subjects(walk, Select(Classpath), variant_subjects,
                                    variants={'thrift': 'apache_java'})

  def test_consumes_resources(self):
    build_request = self.request(['compile'], self.consumes_resources)
    root, = self.build(build_request)

    # Validate the root.
    self.assert_root(root, self.consumes_resources, Classpath, Classpath(creator='javac'))

    # Confirm a classpath for the resources target and other subjects. We know that they are
    # reachable from the root (since it was involved in this walk).
    subjects = [self.resources,
                self.consumes_resources,
                self.guava]
    self.assert_select_for_subjects(walk, Select(Classpath), subjects)

  def test_managed_resolve(self):
    """A managed resolve should consume a ManagedResolve and ManagedJars to produce Jars."""
    build_request = self.request(['compile'], self.consumes_managed_thirdparty)
    root, = self.build(build_request)

    # Validate the root.
    self.assert_root(root, self.consumes_managed_thirdparty, Classpath, Classpath(creator='javac'))

    # Confirm that we produced classpaths for the managed jars.
    managed_jars = [self.managed_guava, self.managed_hadoop]
    self.assert_select_for_subjects(walk, Select(Classpath), [self.consumes_managed_thirdparty])
    self.assert_select_for_subjects(walk, Select(Classpath), managed_jars,
                                    variants={'resolve': 'latest-hadoop'})

    # Confirm that the produced jars had the appropriate versions.
    self.assertEquals({Jar('org.apache.hadoop', 'hadoop-common', '2.7.0'),
                       Jar('com.google.guava', 'guava', '18.0')},
                      {ret.value for node, ret in walk
                       if node.product == Jar})

  def test_dependency_inference(self):
    """Scala dependency inference introduces dependencies that do not exist in BUILD files."""
    build_request = self.request(['compile'], self.inferred_deps)
    root, = self.build(build_request)

    # Validate the root.
    self.assert_root(root, self.inferred_deps, Classpath, Classpath(creator='scalac'))

    # Confirm that we requested a classpath for the root and inferred targets.
    walk = "TODO: Should port this type of internal inspection to the native code."
    self.assert_select_for_subjects(walk, Select(Classpath), [self.inferred_deps, self.java_simple])

  def test_multiple_classpath_entries(self):
    """Multiple Classpath products for a single subject currently cause a failure."""
    build_request = self.request(['compile'], self.java_multi)
    root, = self.build(build_request)

    # Validate that the root failed.
    self.assert_root_failed(root, self.java_multi, Classpath,
                            "TODO: string match for ConflictingProducers failure.")

  def test_descendant_specs(self):
    """Test that Addresses are produced via recursive globs of the 3rdparty/jvm directory."""
    spec = self.spec_parser.parse_spec('3rdparty/jvm::')
    build_request = self.request_specs(['list'], spec)
    ((subject, root_product), root_value), = self.build(build_request)

    # Validate the root.
    self.assertEqual(spec, subject)
    self.assertEqual(root_product, Addresses)
    self.assertEqual(list, type(root_value))

    # Confirm that a few expected addresses are in the list.
    self.assertIn(self.guava, root_value)
    self.assertIn(self.managed_guava, root_value)
    self.assertIn(self.managed_resolve_latest, root_value)

  def test_sibling_specs(self):
    """Test that sibling Addresses are parsed in the 3rdparty/jvm directory."""
    spec = self.spec_parser.parse_spec('3rdparty/jvm:')
    build_request = self.request_specs(['list'], spec)
    ((subject, root_product), root_value), = self.build(build_request)

    # Validate the root.
    self.assertEqual(spec, subject)
    self.assertEqual(root_product, Addresses)
    self.assertEqual(list, type(root_value))

    # Confirm that an expected address is in the list.
    self.assertIn(self.guava, root_value)
    # And that an subdirectory address is not.
    self.assertNotIn(self.managed_guava, root_value)

  def test_scheduler_visualize(self):
    spec = self.spec_parser.parse_spec('3rdparty/jvm:')
    build_request = self.request_specs(['list'], spec)
    self.build_and_walk(build_request)

    graphviz_output = '\n'.join(self.scheduler.product_graph.visualize(build_request.roots))

    with temporary_dir() as td:
      output_path = os.path.join(td, 'output.dot')
      self.scheduler.visualize_graph_to_file(build_request.roots, output_path)
      with open(output_path, 'rb') as fh:
        graphviz_disk_output = fh.read().strip()

    self.assertEqual(graphviz_output, graphviz_disk_output)
    self.assertIn('digraph', graphviz_output)
    self.assertIn(' -> ', graphviz_output)
