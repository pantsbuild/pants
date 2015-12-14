# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from functools import partial

from pants.build_graph.address import Address
from pants.engine.exp.addressable import Exactly, addressable, addressable_dict
from pants.engine.exp.configuration import Configuration
from pants.engine.exp.graph import (CycleError, Graph, ResolvedTypeMismatchError, ResolveError,
                                    Resolver)
from pants.engine.exp.mapper import AddressMapper
from pants.engine.exp.parsers import parse_json, python_assignments_parser, python_callbacks_parser
from pants.engine.exp.targets import Target


class ApacheThriftConfiguration(Configuration):
  # An example of a mixed-mode object - can be directly embedded without a name or else referenced
  # via address if both top-level and carrying a name.
  #
  # Also an example of a more constrained config object that has an explicit set of allowed fields
  # and that can have pydoc hung directly off the constructor to convey a fully accurate BUILD
  # dictionary entry.

  def __init__(self, name=None, version=None, strict=None, lang=None, options=None, **kwargs):
    super(ApacheThriftConfiguration, self).__init__(name=name,
                                                    version=version,
                                                    strict=strict,
                                                    lang=lang,
                                                    options=options,
                                                    **kwargs)

  # An example of a validatable bit of config.
  def validate_concrete(self):
    if not self.version:
      self.report_validation_error('A thrift `version` is required.')
    if not self.lang:
      self.report_validation_error('A thrift gen `lang` is required.')


class PublishConfiguration(Configuration):
  # An example of addressable and addressable_mapping field wrappers.

  def __init__(self, default_repo, repos, name=None, **kwargs):
    super(PublishConfiguration, self).__init__(name=name, **kwargs)
    self.default_repo = default_repo
    self.repos = repos

  @addressable(Exactly(Configuration))
  def default_repo(self):
    """"""

  @addressable_dict(Exactly(Configuration))
  def repos(self):
    """"""


class GraphTestBase(unittest.TestCase):
  def setUp(self):
    self.symbol_table = {'ApacheThriftConfig': ApacheThriftConfiguration,
                         'Config': Configuration,
                         'PublishConfig': PublishConfiguration,
                         'Target': Target}

  def create_graph(self, build_pattern=None, parser=None, inline=False):
    mapper = AddressMapper(build_root=os.path.dirname(__file__),
                           build_pattern=build_pattern,
                           parser=parser)
    return Graph(mapper, inline=inline)

  def create_json_graph(self):
    return self.create_graph(build_pattern=r'.+\.BUILD.json$',
                             parser=partial(parse_json, symbol_table=self.symbol_table))


class InlinedGraphTest(GraphTestBase):
  def create_graph(self, build_pattern=None, parser=None, inline=True):
    return super(InlinedGraphTest, self).create_graph(build_pattern, parser, inline=inline)

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
    thrift1 = Target(address=address('thrift1'))
    thrift2 = Target(address=address('thrift2'), dependencies=[thrift1])
    expected_java1 = Target(address=address('java1'),
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
                              parser=python_assignments_parser(symbol_table=self.symbol_table))
    self.do_test_codegen_simple(graph)

  def test_python_classic(self):
    graph = self.create_graph(build_pattern=r'.+\.BUILD$',
                              parser=python_callbacks_parser(symbol_table=self.symbol_table))
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


class LazyResolvingGraphTest(GraphTestBase):
  def do_test_codegen_simple(self, graph):
    def address(name):
      return Address(spec_path='examples/graph_test', target_name=name)

    def resolver(addr):
      return Resolver(graph, addr)

    java1_address = address('java1')
    resolved_java1 = graph.resolve(java1_address)

    nonstrict_address = address('nonstrict')
    public_address = address('public')
    thrift2_address = address('thrift2')
    expected_java1 = Target(address=java1_address,
                            sources={},
                            configurations=[
                              ApacheThriftConfiguration(version='0.9.2', strict=True, lang='java'),
                              resolver(nonstrict_address),
                              PublishConfiguration(
                                default_repo=resolver(public_address),
                                repos={
                                  'jake':
                                    Configuration(url='https://dl.bintray.com/pantsbuild/maven'),
                                  'jane': resolver(public_address)
                                }
                              )
                            ],
                            dependencies=[resolver(thrift2_address)])

    self.assertEqual(expected_java1, resolved_java1)

    expected_nonstrict = ApacheThriftConfiguration(address=nonstrict_address,
                                                   version='0.9.2',
                                                   strict=False,
                                                   lang='java')
    resolved_nonstrict = graph.resolve(nonstrict_address)
    self.assertEqual(expected_nonstrict, resolved_nonstrict)
    self.assertEqual(expected_nonstrict, expected_java1.configurations[1])
    self.assertIs(expected_java1.configurations[1], resolved_nonstrict)

    expected_public = Configuration(address=public_address,
                                    url='https://oss.sonatype.org/#stagingRepositories')
    resolved_public = graph.resolve(public_address)
    self.assertEqual(expected_public, resolved_public)
    self.assertEqual(expected_public, expected_java1.configurations[2].default_repo)
    self.assertEqual(expected_public, expected_java1.configurations[2].repos['jane'])
    self.assertIs(expected_java1.configurations[2].default_repo, resolved_public)
    self.assertIs(expected_java1.configurations[2].repos['jane'], resolved_public)

    thrift1_address = address('thrift1')
    expected_thrift2 = Target(address=thrift2_address, dependencies=[resolver(thrift1_address)])
    resolved_thrift2 = graph.resolve(thrift2_address)
    self.assertEqual(expected_thrift2, resolved_thrift2)
    self.assertEqual(expected_thrift2, resolved_java1.dependencies[0])
    self.assertIs(resolved_java1.dependencies[0], resolved_thrift2)

    expected_thrift1 = Target(address=thrift1_address)
    resolved_thrift1 = graph.resolve(thrift1_address)
    self.assertEqual(expected_thrift1, resolved_thrift1)
    self.assertEqual(expected_thrift1, resolved_thrift2.dependencies[0])
    self.assertIs(resolved_thrift2.dependencies[0], resolved_thrift1)

  def test_json(self):
    graph = self.create_json_graph()
    self.do_test_codegen_simple(graph)

  def test_python(self):
    graph = self.create_graph(build_pattern=r'.+\.BUILD.python$',
                              parser=python_assignments_parser(symbol_table=self.symbol_table))
    self.do_test_codegen_simple(graph)

  def test_python_classic(self):
    graph = self.create_graph(build_pattern=r'.+\.BUILD$',
                              parser=python_callbacks_parser(symbol_table=self.symbol_table))
    self.do_test_codegen_simple(graph)
