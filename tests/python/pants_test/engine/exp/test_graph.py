# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from functools import partial

from pants.base.address import Address
from pants.engine.exp.configuration import Configuration
from pants.engine.exp.graph import CycleError, Graph, ResolvedTypeMismatchError, ResolveError
from pants.engine.exp.parsers import parse_json, python_assignments_parser, python_callbacks_parser
from pants.engine.exp.targets import ApacheThriftConfiguration, PublishConfiguration, Target


class GraphTest(unittest.TestCase):
  def setUp(self):
    self.symbol_table = {'ApacheThriftConfig': ApacheThriftConfiguration,
                         'Config': Configuration,
                         'Target': Target,
                         'PublishConfig': PublishConfiguration}

  def create_graph(self, build_pattern=None, parser=None):
    return Graph(build_root=os.path.dirname(__file__), build_pattern=build_pattern, parser=parser)

  def create_json_graph(self):
    return self.create_graph(build_pattern=r'.+\.BUILD.json$',
                             parser=partial(parse_json, symbol_table=self.symbol_table))

  def do_test_codegen_simple(self, graph):
    def address(name):
      return Address(spec_path='examples/graph_test', target_name=name)

    resolved_java1 = graph.resolve(address('java1'))

    nonstrict = ApacheThriftConfiguration(address=address('nonstrict'),
                                          version='0.9.2',
                                          strict=False,
                                          lang='java')
    public = Configuration(address=address('public'),
                           url='https://oss.sonatype.org/#stagingRepositories')
    thrift1 = Target(address=address('thrift1'), sources=[])
    thrift2 = Target(address=address('thrift2'), sources=[], dependencies=[thrift1])
    expected_java1 = Target(address=address('java1'),
                            sources=[],
                            configurations=[
                              ApacheThriftConfiguration(version='0.9.2', strict=True, lang='java'),
                              nonstrict,
                              PublishConfiguration(
                                default_repo=public,
                                repos={
                                  'jake':
                                    Configuration(url='https://dl.bintray.com/pantsbuild/maven'),
                                  'jane': public
                                }
                              )
                            ],
                            dependencies=[thrift2])

    self.assertEqual(expected_java1, resolved_java1)

  def test_json(self):
    graph = self.create_json_graph()
    self.do_test_codegen_simple(graph)

  def test_python(self):
    graph = self.create_graph(build_pattern=r'.+\.BUILD.python$',
                              parser=python_assignments_parser(self.symbol_table))
    self.do_test_codegen_simple(graph)

  def test_python_classic(self):
    graph = self.create_graph(build_pattern=r'.+\.BUILD$',
                              parser=python_callbacks_parser(self.symbol_table))
    self.do_test_codegen_simple(graph)

  def test_resolve_cache(self):
    graph = self.create_json_graph()

    nonstrict_address = Address.parse('examples/graph_test:nonstrict')
    nonstrict = graph.resolve(nonstrict_address)
    self.assertIs(nonstrict, graph.resolve(nonstrict_address))

    # The already resolved `nonstrict` interior node should be re-used by `java1`.
    java1_address = Address.parse('examples/graph_test:java1')
    java1 = graph.resolve(java1_address)
    self.assertIs(nonstrict, java1.configurations[1])

    self.assertIs(java1, graph.resolve(java1_address))

  def extract_path_tail(self, cycle_exception, line_count):
    return [l.lstrip() for l in str(cycle_exception).splitlines()[-line_count:]]

  def test_cycle_self(self):
    graph = self.create_json_graph()
    with self.assertRaises(CycleError) as exc:
      graph.resolve(Address.parse('examples/graph_test:self_cycle'))
    self.assertEqual(['* examples/graph_test:self_cycle',
                      '* examples/graph_test:self_cycle'],
                     self.extract_path_tail(exc.exception, 2))

  def test_cycle_direct(self):
    graph = self.create_json_graph()
    with self.assertRaises(CycleError) as exc:
      graph.resolve(Address.parse('examples/graph_test:direct_cycle'))
    self.assertEqual(['* examples/graph_test:direct_cycle',
                      'examples/graph_test:direct_cycle_dep',
                      '* examples/graph_test:direct_cycle'],
                     self.extract_path_tail(exc.exception, 3))

  def test_cycle_indirect(self):
    graph = self.create_json_graph()
    with self.assertRaises(CycleError) as exc:
      graph.resolve(Address.parse('examples/graph_test:indirect_cycle'))
    self.assertEqual(['examples/graph_test:indirect_cycle',
                      '* examples/graph_test:one',
                      'examples/graph_test:two',
                      'examples/graph_test:three',
                      '* examples/graph_test:one'],
                     self.extract_path_tail(exc.exception, 5))

  def test_type_mismatch_error(self):
    graph = self.create_json_graph()
    with self.assertRaises(ResolvedTypeMismatchError):
      graph.resolve(Address.parse('examples/graph_test:type_mismatch'))

  def test_not_found_but_family_exists(self):
    graph = self.create_json_graph()
    with self.assertRaises(ResolveError):
      graph.resolve(Address.parse('examples/graph_test:this_addressable_does_not_exist'))

  def test_not_found_and_family_does_not_exist(self):
    graph = self.create_json_graph()
    with self.assertRaises(ResolveError):
      graph.resolve(Address.parse('this/dir/does/not/exist'))
