# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
import unittest

from pants.base.project_tree import Dir, File
from pants.base.specs import SiblingAddresses, SingleAddress, Specs
from pants.build_graph.address import Address
from pants.engine.addressable import addressable, addressable_dict
from pants.engine.build_files import (ResolvedTypeMismatchError, addresses_from_address_families,
                                      create_graph_rules, parse_address_family)
from pants.engine.fs import (DirectoryDigest, FileContent, FilesContent, Path, PathGlobs, Snapshot,
                             create_fs_rules)
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.mapper import AddressFamily, AddressMapper, ResolveError
from pants.engine.nodes import Return, Throw
from pants.engine.parser import SymbolTable
from pants.engine.struct import Struct, StructWithDeps
from pants.util.objects import Exactly
from pants_test.engine.examples.parsers import (JsonParser, PythonAssignmentsParser,
                                                PythonCallbacksParser)
from pants_test.engine.scheduler_test_base import SchedulerTestBase
from pants_test.engine.util import Target, run_rule


class ParseAddressFamilyTest(unittest.TestCase):
  def test_empty(self):
    """Test that parsing an empty BUILD file results in an empty AddressFamily."""
    address_mapper = AddressMapper(JsonParser(TestTable()))
    af = run_rule(parse_address_family, address_mapper, Dir('/dev/null'), {
        (Snapshot, PathGlobs): lambda _: Snapshot(DirectoryDigest('abc', 10), (File('/dev/null/BUILD'),)),
        (FilesContent, DirectoryDigest): lambda _: FilesContent([FileContent('/dev/null/BUILD', b'')]),
      })
    self.assertEqual(len(af.objects_by_name), 0)


class AddressesFromAddressFamiliesTest(unittest.TestCase):

  def _address_mapper(self):
    return AddressMapper(JsonParser(TestTable()))

  def _snapshot(self):
    return Snapshot(
      DirectoryDigest('xx', 2),
      (Path('root/BUILD', File('root/BUILD')),))

  def _resolve_build_file_addresses(self, specs, address_family, snapshot, address_mapper):
    return run_rule(addresses_from_address_families, address_mapper, specs, {
      (Snapshot, PathGlobs): lambda _: snapshot,
      (AddressFamily, Dir): lambda _: address_family,
    })

  def test_duplicated(self):
    """Test that matching the same Spec twice succeeds."""
    address = SingleAddress('a', 'a')
    snapshot = Snapshot(DirectoryDigest('xx', 2),
                        (Path('a/BUILD', File('a/BUILD')),))
    address_family = AddressFamily('a', {'a': ('a/BUILD', 'this is an object!')})
    specs = Specs([address, address])

    bfas = self._resolve_build_file_addresses(
      specs, address_family, snapshot, self._address_mapper())

    self.assertEqual(len(bfas.dependencies), 1)
    self.assertEqual(bfas.dependencies[0].spec, 'a:a')

  def test_tag_filter(self):
    """Test that targets are filtered based on `tags`."""
    specs = Specs([SiblingAddresses('root')], tags=['+integration'])
    address_family = AddressFamily('root',
      {'a': ('root/BUILD', TargetAdaptor()),
       'b': ('root/BUILD', TargetAdaptor(tags={'integration'})),
       'c': ('root/BUILD', TargetAdaptor(tags={'not_integration'}))
      }
    )

    targets = self._resolve_build_file_addresses(
      specs, address_family, self._snapshot(), self._address_mapper())

    self.assertEqual(len(targets.dependencies), 1)
    self.assertEqual(targets.dependencies[0].spec, 'root:b')

  def test_fails_on_nonexistent_specs(self):
    """Test that specs referring to nonexistent targets raise a ResolveError."""
    address_family = AddressFamily('root', {'a': ('root/BUILD', TargetAdaptor())})
    specs = Specs([SingleAddress('root', 'b'), SingleAddress('root', 'a')])

    expected_rx_str = re.escape(
      """"b" was not found in namespace "root". Did you mean one of:
  :a""")
    with self.assertRaisesRegexp(ResolveError, expected_rx_str):
      self._resolve_build_file_addresses(
        specs, address_family, self._snapshot(), self._address_mapper())

    # Ensure that we still catch nonexistent targets later on in the list of command-line specs.
    specs = Specs([SingleAddress('root', 'a'), SingleAddress('root', 'b')])
    with self.assertRaisesRegexp(ResolveError, expected_rx_str):
      self._resolve_build_file_addresses(
        specs, address_family, self._snapshot(), self._address_mapper())

  def test_exclude_pattern(self):
    """Test that targets are filtered based on exclude patterns."""
    specs = Specs([SiblingAddresses('root')], exclude_patterns=tuple(['.exclude*']))
    address_family = AddressFamily('root',
                                   {'exclude_me': ('root/BUILD', TargetAdaptor()),
                                    'not_me': ('root/BUILD', TargetAdaptor()),
                                   }
    )

    targets = self._resolve_build_file_addresses(
      specs, address_family, self._snapshot(), self._address_mapper())

    self.assertEqual(len(targets.dependencies), 1)
    self.assertEqual(targets.dependencies[0].spec, 'root:not_me')

  def test_exclude_pattern_with_single_address(self):
    """Test that single address targets are filtered based on exclude patterns."""
    specs = Specs([SingleAddress('root', 'not_me')], exclude_patterns=tuple(['root.*']))
    address_family = AddressFamily('root',
                                   {
                                     'not_me': ('root/BUILD', TargetAdaptor()),
                                   }
    )

    targets = self._resolve_build_file_addresses(
      specs, address_family, self._snapshot(), self._address_mapper())

    self.assertEqual(len(targets.dependencies), 0)


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
  def table(self):
    return {'ApacheThriftConfig': ApacheThriftConfiguration,
            'Struct': Struct,
            'StructWithDeps': StructWithDeps,
            'PublishConfig': PublishConfiguration,
            'Target': Target}


class GraphTestBase(unittest.TestCase, SchedulerTestBase):
  def create(self, build_patterns=None, parser=None):
    address_mapper = AddressMapper(build_patterns=build_patterns,
                                   parser=parser)
    symbol_table = address_mapper.parser.symbol_table

    rules = create_fs_rules() + create_graph_rules(address_mapper, symbol_table)
    project_tree = self.mk_fs_tree(os.path.join(os.path.dirname(__file__), 'examples'))
    scheduler = self.mk_scheduler(rules=rules, project_tree=project_tree)
    return scheduler

  def create_json(self):
    return self.create(build_patterns=('*.BUILD.json',), parser=JsonParser(TestTable()))

  def _populate(self, scheduler, address):
    """Perform an ExecutionRequest to parse the given Address into a Struct."""
    request = scheduler.execution_request([TestTable().constraint()], [address])
    root_entries = scheduler.execute(request).root_products
    self.assertEqual(1, len(root_entries))
    return request, root_entries[0][1]

  def resolve_failure(self, scheduler, address):
    _, state = self._populate(scheduler, address)
    self.assertEqual(type(state), Throw, '{} is not a Throw.'.format(state))
    return state.exc

  def resolve(self, scheduler, address):
    _, state = self._populate(scheduler, address)
    self.assertEqual(type(state), Return, '{} is not a Return.'.format(state))
    return state.value


class InlinedGraphTest(GraphTestBase):

  def do_test_codegen_simple(self, scheduler):
    def address(name):
      return Address(spec_path='graph_test', target_name=name)

    resolved_java1 = self.resolve(scheduler, address('java1'))

    nonstrict = ApacheThriftConfiguration(type_alias='ApacheThriftConfig',
                                          address=address('nonstrict'),
                                          version='0.9.2',
                                          strict=False,
                                          lang='java')
    public = Struct(type_alias='Struct',
                    address=address('public'),
                    url='https://oss.sonatype.org/#stagingRepositories')
    thrift1 = Target(address=address('thrift1'))
    thrift2 = Target(address=address('thrift2'), dependencies=[thrift1])
    expected_java1 = Target(address=address('java1'),
                            configurations=[
                              PublishConfiguration(
                                type_alias='PublishConfig',
                                default_repo=public,
                                repos={
                                  'jake':
                                    Struct(type_alias='Struct', url='https://dl.bintray.com/pantsbuild/maven'),
                                  'jane': public
                                }
                              ),
                              nonstrict,
                              ApacheThriftConfiguration(type_alias='ApacheThriftConfig',
                                                        version='0.9.2',
                                                        strict=True,
                                                        dependencies=[address('thrift2')],
                                                        lang='java'),
                            ],
                            dependencies=[thrift2],
                            type_alias='Target')

    self.assertEqual(expected_java1.configurations, resolved_java1.configurations)

  def test_json(self):
    scheduler = self.create_json()
    self.do_test_codegen_simple(scheduler)

  def test_python(self):
    scheduler = self.create(build_patterns=('*.BUILD.python',),
                            parser=PythonAssignmentsParser(TestTable()))
    self.do_test_codegen_simple(scheduler)

  def test_python_classic(self):
    scheduler = self.create(build_patterns=('*.BUILD',),
                            parser=PythonCallbacksParser(TestTable()))
    self.do_test_codegen_simple(scheduler)

  def test_resolve_cache(self):
    scheduler = self.create_json()

    nonstrict_address = Address.parse('graph_test:nonstrict')
    nonstrict = self.resolve(scheduler, nonstrict_address)
    self.assertEqual(nonstrict, self.resolve(scheduler, nonstrict_address))

    # The already resolved `nonstrict` interior node should be re-used by `java1`.
    java1_address = Address.parse('graph_test:java1')
    java1 = self.resolve(scheduler, java1_address)
    self.assertEqual(nonstrict, java1.configurations[1])

    self.assertEqual(java1, self.resolve(scheduler, java1_address))

  def do_test_trace_message(self, scheduler, parsed_address, expected_string=None):
    # Confirm that the root failed, and that a cycle occurred deeper in the graph.
    request, state = self._populate(scheduler, parsed_address)
    self.assertEqual(type(state), Throw)
    trace_message = '\n'.join(scheduler.trace(request))

    self.assert_throws_are_leaves(trace_message, Throw.__name__)
    if expected_string:
      self.assertIn(expected_string, trace_message)

  def do_test_cycle(self, address_str):
    scheduler = self.create_json()
    parsed_address = Address.parse(address_str)
    self.do_test_trace_message(scheduler, parsed_address, 'Dep graph contained a cycle.')

  def assert_throws_are_leaves(self, error_msg, throw_name):
    def indent_of(s):
      return len(s) - len(s.lstrip())

    def assert_equal_or_more_indentation(more_indented_line, less_indented_line):
      self.assertTrue(indent_of(more_indented_line) >= indent_of(less_indented_line),
                      '\n"{}"\nshould have more equal or more indentation than\n"{}"\n{}'.format(more_indented_line,
                                                                                             less_indented_line, error_msg))

    lines = error_msg.splitlines()
    line_indices_of_throws = [i for i, v in enumerate(lines) if throw_name in v]
    for idx in line_indices_of_throws:
      # Make sure lines with Throw have more or equal indentation than its neighbors.
      current_line = lines[idx]
      line_above = lines[max(0, idx - 1)]

      assert_equal_or_more_indentation(current_line, line_above)

  def test_cycle_self(self):
    self.do_test_cycle('graph_test:self_cycle')

  def test_cycle_direct(self):
    self.do_test_cycle('graph_test:direct_cycle')

  def test_cycle_indirect(self):
    self.do_test_cycle('graph_test:indirect_cycle')

  def test_type_mismatch_error(self):
    scheduler = self.create_json()
    mismatch = Address.parse('graph_test:type_mismatch')
    self.assert_resolve_failure_type(ResolvedTypeMismatchError, mismatch, scheduler)
    self.do_test_trace_message(scheduler, mismatch)

  def test_not_found_but_family_exists(self):
    scheduler = self.create_json()
    dne = Address.parse('graph_test:this_addressable_does_not_exist')
    self.assert_resolve_failure_type(ResolveError, dne, scheduler)
    self.do_test_trace_message(scheduler, dne)

  def test_not_found_and_family_does_not_exist(self):
    scheduler = self.create_json()
    dne = Address.parse('this/dir/does/not/exist')
    self.assert_resolve_failure_type(ResolveError, dne, scheduler)
    self.do_test_trace_message(scheduler, dne)

  def assert_resolve_failure_type(self, expected_type, mismatch, scheduler):

    failure = self.resolve_failure(scheduler, mismatch)
    self.assertEqual(type(failure),
                      expected_type,
                      'type was not {}. Instead was {}, {!r}'.format(expected_type.__name__, type(failure).__name__, failure))
