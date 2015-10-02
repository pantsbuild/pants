# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from functools import partial

from pants.base.address import Address
from pants.engine.exp.graph import Graph
from pants.engine.exp.parsers import parse_json, parse_python_assignments, parse_python_callbacks
from pants.engine.exp.targets import ApacheThriftConfig, Config, PublishConfig, Target


class GraphTest(unittest.TestCase):
  def setUp(self):
    self.symbol_table = {type_.__name__: type_
                         for type_ in (ApacheThriftConfig, Config, Target, PublishConfig)}

  def create_graph(self, build_pattern=None, parser=None):
    return Graph(build_root=os.path.dirname(__file__), build_pattern=build_pattern, parser=parser)

  def do_test_codegen_simple(self, graph):
    resolved_java1 = graph.resolve(Address.parse('examples/graph_test:java1'))

    nonstrict = ApacheThriftConfig(name='nonstrict',
                                   version='0.9.2',
                                   strict=False,
                                   lang='java')
    public = Config(name='public', url='https://oss.sonatype.org/#stagingRepositories')
    thrift1 = Target(name='thrift1', sources=[])
    thrift2 = Target(name='thrift2', sources=[], dependencies=[thrift1])
    expected_java1 = Target(name='java1',
                            sources=[],
                            configurations=[
                              ApacheThriftConfig(version='0.9.2', strict=True, lang='java'),
                              nonstrict,
                              PublishConfig(
                                default_repo=public,
                                repos={
                                  'jake': Config(url='https://dl.bintray.com/pantsbuild/maven'),
                                  'jane': public
                                }
                              )
                            ],
                            dependencies=[thrift2])

    self.assertEqual(expected_java1, resolved_java1)

  def test_json(self):
    graph = self.create_graph(build_pattern=r'.+\.BUILD.json$',
                              parser=partial(parse_json, symbol_table=self.symbol_table))
    self.do_test_codegen_simple(graph)

  def test_python(self):
    graph = self.create_graph(build_pattern=r'.+\.BUILD.python$',
                              parser=partial(parse_python_assignments,
                                             symbol_table=self.symbol_table))
    self.do_test_codegen_simple(graph)

  def test_python_classic(self):
    graph = self.create_graph(build_pattern=r'.+\.BUILD$',
                              parser=partial(parse_python_callbacks,
                                             symbol_table=self.symbol_table))
    self.do_test_codegen_simple(graph)
