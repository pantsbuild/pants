# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.build_graph.address import Address
from pants.engine.exp.addressable import Exactly, addressable, addressable_dict
from pants.engine.exp.engine import LocalSerialEngine
from pants.engine.exp.graph import ResolvedTypeMismatchError, create_graph_tasks
from pants.engine.exp.mapper import AddressMapper, ResolveError
from pants.engine.exp.parsers import (JsonParser, PythonAssignmentsParser, PythonCallbacksParser,
                                      SymbolTable)
from pants.engine.exp.scheduler import BuildRequest, LocalScheduler, Return, SelectNode
from pants.engine.exp.struct import Struct, StructWithDeps
from pants.engine.exp.targets import Target


class ApacheThriftConfiguration(StructWithDeps):
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


class PublishConfiguration(Struct):
  # An example of addressable and addressable_mapping field wrappers.

  def __init__(self, default_repo, repos, name=None, **kwargs):
    super(PublishConfiguration, self).__init__(name=name, **kwargs)
    self.default_repo = default_repo
    self.repos = repos

  @addressable(Exactly(Struct))
  def default_repo(self):
    """"""

  @addressable_dict(Exactly(Struct))
  def repos(self):
    """"""


class TestTable(SymbolTable):
  @classmethod
  def table(cls):
    return {'ApacheThriftConfig': ApacheThriftConfiguration,
            'Struct': Struct,
            'StructWithDeps': StructWithDeps,
            'PublishConfig': PublishConfiguration,
            'Target': Target}


class GraphTestBase(unittest.TestCase):
  _goal = 'parse'
  _product = Struct

  def _select(self, address):
    return SelectNode(address, self._product, None, None)

  def create(self, build_pattern=None, parser_cls=None, inline=False):
    mapper = AddressMapper(build_root=os.path.dirname(__file__),
                           symbol_table_cls=TestTable,
                           build_pattern=build_pattern,
                           parser_cls=parser_cls)
    return LocalScheduler({self._goal: [self._product]}, create_graph_tasks(mapper))

  def create_json(self):
    return self.create(build_pattern=r'.+\.BUILD.json$', parser_cls=JsonParser)

  def resolve(self, scheduler, address):
    """Make a BuildRequest to parse the given Address into a Struct."""
    request = BuildRequest(goals=[self._goal], addressable_roots=[address])
    LocalSerialEngine(scheduler).reduce(request)
    state = scheduler.product_graph.state(self._select(address))
    self.assertEquals(type(state), Return, '{} is not a Return.'.format(state))
    return state.value


class InlinedGraphTest(GraphTestBase):
  def create(self, build_pattern=None, parser_cls=None, inline=True):
    return super(InlinedGraphTest, self).create(build_pattern, parser_cls, inline=inline)

  def do_test_codegen_simple(self, scheduler):
    def address(name):
      return Address(spec_path='examples/graph_test', target_name=name)

    resolved_java1 = self.resolve(scheduler, address('java1'))

    nonstrict = ApacheThriftConfiguration(address=address('nonstrict'),
                                          version='0.9.2',
                                          strict=False,
                                          lang='java')
    public = Struct(address=address('public'),
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
                                    Struct(url='https://dl.bintray.com/pantsbuild/maven'),
                                  'jane': public
                                }
                              )
                            ],
                            dependencies=[thrift2])

    self.assertEqual(expected_java1, resolved_java1)

  def test_json(self):
    scheduler = self.create_json()
    self.do_test_codegen_simple(scheduler)

  def test_python(self):
    scheduler = self.create(build_pattern=r'.+\.BUILD.python$',
                            parser_cls=PythonAssignmentsParser)
    self.do_test_codegen_simple(scheduler)

  def test_python_classic(self):
    scheduler = self.create(build_pattern=r'.+\.BUILD$',
                            parser_cls=PythonCallbacksParser)
    self.do_test_codegen_simple(scheduler)

  def test_resolve_cache(self):
    scheduler = self.create_json()

    nonstrict_address = Address.parse('examples/graph_test:nonstrict')
    nonstrict = self.resolve(scheduler, nonstrict_address)
    self.assertIs(nonstrict, self.resolve(scheduler, nonstrict_address))

    # The already resolved `nonstrict` interior node should be re-used by `java1`.
    java1_address = Address.parse('examples/graph_test:java1')
    java1 = self.resolve(scheduler, java1_address)
    self.assertIs(nonstrict, java1.configurations[1])

    self.assertIs(java1, self.resolve(scheduler, java1_address))

  def extract_path_tail(self, cycle_exception, line_count):
    return [l.lstrip() for l in str(cycle_exception).splitlines()[-line_count:]]

  def test_cycle_self(self):
    scheduler = self.create_json()
    with self.assertRaises(CycleError) as exc:
      self.resolve(scheduler, Address.parse('examples/graph_test:self_cycle'))
    self.assertEqual(['* examples/graph_test:self_cycle',
                      '* examples/graph_test:self_cycle'],
                     self.extract_path_tail(exc.exception, 2))

  def test_cycle_direct(self):
    scheduler = self.create_json()
    with self.assertRaises(CycleError) as exc:
      self.resolve(scheduler, Address.parse('examples/graph_test:direct_cycle'))
    self.assertEqual(['* examples/graph_test:direct_cycle',
                      'examples/graph_test:direct_cycle_dep',
                      '* examples/graph_test:direct_cycle'],
                     self.extract_path_tail(exc.exception, 3))

  def test_cycle_indirect(self):
    scheduler = self.create_json()
    with self.assertRaises(CycleError) as exc:
      self.resolve(scheduler, Address.parse('examples/graph_test:indirect_cycle'))
    self.assertEqual(['examples/graph_test:indirect_cycle',
                      '* examples/graph_test:one',
                      'examples/graph_test:two',
                      'examples/graph_test:three',
                      '* examples/graph_test:one'],
                     self.extract_path_tail(exc.exception, 5))

  def test_type_mismatch_error(self):
    scheduler = self.create_json()
    with self.assertRaises(ResolvedTypeMismatchError):
      self.resolve(scheduler, Address.parse('examples/graph_test:type_mismatch'))

  def test_not_found_but_family_exists(self):
    scheduler = self.create_json()
    with self.assertRaises(ResolveError):
      self.resolve(scheduler, Address.parse('examples/graph_test:this_addressable_does_not_exist'))

  def test_not_found_and_family_does_not_exist(self):
    scheduler = self.create_json()
    with self.assertRaises(ResolveError):
      self.resolve(scheduler, Address.parse('this/dir/does/not/exist'))


class LazyResolvingGraphTest(GraphTestBase):
  def do_test_codegen_simple(self, scheduler):
    def address(name):
      return Address(spec_path='examples/graph_test', target_name=name)

    java1_address = address('java1')
    resolved_java1 = self.resolve(scheduler, java1_address)

    nonstrict_address = address('nonstrict')
    public_address = address('public')
    thrift2_address = address('thrift2')
    expected_java1 = Target(address=java1_address,
                            sources={},
                            configurations=[
                              ApacheThriftConfiguration(
                                version='0.9.2',
                                strict=True,
                                lang='java',
                                dependencies=[resolver(thrift2_address)]
                              ),
                              resolver(nonstrict_address),
                              PublishConfiguration(
                                default_repo=resolver(public_address),
                                repos={
                                  'jake':
                                    Struct(url='https://dl.bintray.com/pantsbuild/maven'),
                                  'jane': resolver(public_address)
                                }
                              )
                            ])

    self.assertEqual(expected_java1, resolved_java1)

    expected_nonstrict = ApacheThriftConfiguration(address=nonstrict_address,
                                                   version='0.9.2',
                                                   strict=False,
                                                   lang='java')
    resolved_nonstrict = self.resolve(scheduler, nonstrict_address)
    self.assertEqual(expected_nonstrict, resolved_nonstrict)
    self.assertEqual(expected_nonstrict, expected_java1.configurations[1])
    self.assertIs(expected_java1.configurations[1], resolved_nonstrict)

    expected_public = Struct(address=public_address,
                                    url='https://oss.sonatype.org/#stagingRepositories')
    resolved_public = self.resolve(scheduler, public_address)
    self.assertEqual(expected_public, resolved_public)
    self.assertEqual(expected_public, expected_java1.configurations[2].default_repo)
    self.assertEqual(expected_public, expected_java1.configurations[2].repos['jane'])
    self.assertIs(expected_java1.configurations[2].default_repo, resolved_public)
    self.assertIs(expected_java1.configurations[2].repos['jane'], resolved_public)

    thrift1_address = address('thrift1')
    expected_thrift2 = Target(address=thrift2_address, dependencies=[resolver(thrift1_address)])
    resolved_thrift2 = self.resolve(scheduler, thrift2_address)
    self.assertEqual(expected_thrift2, resolved_thrift2)
    resolved_thrift_config = [config for config in resolved_java1.configurations
                              if isinstance(config, ApacheThriftConfiguration)]
    self.assertEqual(expected_thrift2, resolved_thrift_config[0].dependencies[0])
    self.assertIs(resolved_thrift_config[0].dependencies[0], resolved_thrift2)

    expected_thrift1 = Target(address=thrift1_address)
    resolved_thrift1 = self.resolve(scheduler, thrift1_address)
    self.assertEqual(expected_thrift1, resolved_thrift1)
    self.assertEqual(expected_thrift1, resolved_thrift2.dependencies[0])
    self.assertIs(resolved_thrift2.dependencies[0], resolved_thrift1)

  def test_json(self):
    scheduler = self.create_json()
    self.do_test_codegen_simple(scheduler)

  def test_python(self):
    scheduler = self.create(build_pattern=r'.+\.BUILD.python$',
                            parser_cls=PythonAssignmentsParser)
    self.do_test_codegen_simple(scheduler)

  def test_python_classic(self):
    scheduler = self.create(build_pattern=r'.+\.BUILD$',
                            parser_cls=PythonCallbacksParser)
    self.do_test_codegen_simple(scheduler)
