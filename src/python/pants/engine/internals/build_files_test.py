# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import unittest
import unittest.mock
from textwrap import dedent
from typing import Tuple, Type, cast

from pants.base.exceptions import ResolveError
from pants.base.project_tree import Dir
from pants.base.specs import AddressSpecs, SiblingAddresses, SingleAddress
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import Digest, FileContent, FilesContent, PathGlobs, Snapshot, create_fs_rules
from pants.engine.internals.addressable import addressable
from pants.engine.internals.build_files import (
    ResolvedTypeMismatchError,
    addresses_with_origins_from_address_families,
    create_graph_rules,
    evaluate_preludes,
    parse_address_family,
    strip_address_origins,
)
from pants.engine.internals.examples.parsers import (
    JsonParser,
    PythonAssignmentsParser,
    PythonCallbacksParser,
)
from pants.engine.internals.mapper import AddressFamily, AddressMapper
from pants.engine.internals.nodes import Return, State, Throw
from pants.engine.internals.parser import BuildFilePreludeSymbols, HydratedStruct, SymbolTable
from pants.engine.internals.scheduler import ExecutionError, ExecutionRequest, SchedulerSession
from pants.engine.internals.scheduler_test_base import SchedulerTestBase
from pants.engine.internals.struct import Struct, StructWithDeps
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.rules import rule
from pants.testutil.engine.util import MockGet, Target, run_rule
from pants.util.frozendict import FrozenDict
from pants.util.objects import Exactly


class ParseAddressFamilyTest(unittest.TestCase):
    def test_empty(self) -> None:
        """Test that parsing an empty BUILD file results in an empty AddressFamily."""
        address_mapper = AddressMapper(parser=JsonParser(TEST_TABLE), prelude_glob_patterns=())
        af = run_rule(
            parse_address_family,
            rule_args=[address_mapper, BuildFilePreludeSymbols(FrozenDict()), Dir("/dev/null")],
            mock_gets=[
                MockGet(
                    product_type=Snapshot,
                    subject_type=PathGlobs,
                    mock=lambda _: Snapshot(Digest("abc", 10), ("/dev/null/BUILD",), ()),
                ),
                MockGet(
                    product_type=FilesContent,
                    subject_type=Digest,
                    mock=lambda _: FilesContent([FileContent(path="/dev/null/BUILD", content=b"")]),
                ),
            ],
        )
        self.assertEqual(len(af.objects_by_name), 0)


class AddressesFromAddressFamiliesTest(unittest.TestCase):
    def _address_mapper(self) -> AddressMapper:
        return AddressMapper(JsonParser(TEST_TABLE), prelude_glob_patterns=())

    def _snapshot(self) -> Snapshot:
        return Snapshot(Digest("xx", 2), ("root/BUILD",), ())

    def _resolve_addresses(
        self,
        address_specs: AddressSpecs,
        address_family: AddressFamily,
        snapshot: Snapshot,
        address_mapper: AddressMapper,
    ) -> Addresses:
        addresses_with_origins = run_rule(
            addresses_with_origins_from_address_families,
            rule_args=[address_mapper, address_specs],
            mock_gets=[
                MockGet(product_type=Snapshot, subject_type=PathGlobs, mock=lambda _: snapshot,),
                MockGet(
                    product_type=AddressFamily, subject_type=Dir, mock=lambda _: address_family,
                ),
            ],
        )
        return cast(Addresses, run_rule(strip_address_origins, rule_args=[addresses_with_origins]))

    def test_duplicated(self) -> None:
        """Test that matching the same AddressSpec twice succeeds."""
        address = SingleAddress("a", "a")
        snapshot = Snapshot(Digest("xx", 2), ("a/BUILD",), ())
        address_family = AddressFamily("a", {"a": ("a/BUILD", "this is an object!")})
        address_specs = AddressSpecs([address, address])

        addresses = self._resolve_addresses(
            address_specs, address_family, snapshot, self._address_mapper()
        )
        assert len(addresses) == 1
        assert addresses[0].spec == "a:a"

    def test_tag_filter(self) -> None:
        """Test that targets are filtered based on `tags`."""
        address_specs = AddressSpecs([SiblingAddresses("root")], tags=["+integration"])
        address_family = AddressFamily(
            "root",
            {
                "a": ("root/BUILD", TargetAdaptor()),
                "b": ("root/BUILD", TargetAdaptor(tags={"integration"})),
                "c": ("root/BUILD", TargetAdaptor(tags={"not_integration"})),
            },
        )

        targets = self._resolve_addresses(
            address_specs, address_family, self._snapshot(), self._address_mapper()
        )
        assert len(targets) == 1
        assert targets[0].spec == "root:b"

    def test_fails_on_nonexistent_specs(self) -> None:
        """Test that address specs referring to nonexistent targets raise a ResolveError."""
        address_family = AddressFamily("root", {"a": ("root/BUILD", TargetAdaptor())})
        address_specs = AddressSpecs([SingleAddress("root", "b"), SingleAddress("root", "a")])

        expected_rx_str = re.escape(
            '"b" was not found in namespace "root". Did you mean one of:\n  :a'
        )
        with self.assertRaisesRegex(ResolveError, expected_rx_str):
            self._resolve_addresses(
                address_specs, address_family, self._snapshot(), self._address_mapper()
            )

        # Ensure that we still catch nonexistent targets later on in the list of command-line
        # address specs.
        address_specs = AddressSpecs([SingleAddress("root", "a"), SingleAddress("root", "b")])
        with self.assertRaisesRegex(ResolveError, expected_rx_str):
            self._resolve_addresses(
                address_specs, address_family, self._snapshot(), self._address_mapper()
            )

    def test_exclude_pattern(self) -> None:
        """Test that targets are filtered based on exclude patterns."""
        address_specs = AddressSpecs(
            [SiblingAddresses("root")], exclude_patterns=tuple([".exclude*"])
        )
        address_family = AddressFamily(
            "root",
            {
                "exclude_me": ("root/BUILD", TargetAdaptor()),
                "not_me": ("root/BUILD", TargetAdaptor()),
            },
        )

        targets = self._resolve_addresses(
            address_specs, address_family, self._snapshot(), self._address_mapper()
        )
        assert len(targets) == 1
        assert targets[0].spec == "root:not_me"

    def test_exclude_pattern_with_single_address(self) -> None:
        """Test that single address targets are filtered based on exclude patterns."""
        address_specs = AddressSpecs(
            [SingleAddress("root", "not_me")], exclude_patterns=tuple(["root.*"])
        )
        address_family = AddressFamily("root", {"not_me": ("root/BUILD", TargetAdaptor())})

        targets = self._resolve_addresses(
            address_specs, address_family, self._snapshot(), self._address_mapper()
        )
        assert len(targets.dependencies) == 0


class ApacheThriftConfiguration(StructWithDeps):
    # An example of a mixed-mode object - can be directly embedded without a name or else referenced
    # via address if both top-level and carrying a name.
    #
    # Also an example of a more constrained config object that has an explicit set of allowed fields
    # and that can have pydoc hung directly off the constructor to convey a fully accurate BUILD
    # dictionary entry.

    def __init__(self, name=None, version=None, strict=None, lang=None, options=None, **kwargs):
        super().__init__(
            name=name, version=version, strict=strict, lang=lang, options=options, **kwargs
        )

    # An example of a validatable bit of config.
    def validate_concrete(self):
        if not self.version:
            self.report_validation_error("A thrift `version` is required.")
        if not self.lang:
            self.report_validation_error("A thrift gen `lang` is required.")


class PublishConfiguration(Struct):
    # An example of addressable and addressable_mapping field wrappers.

    def __init__(self, default_repo, name=None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.default_repo = default_repo

    @addressable(Exactly(Struct))
    def default_repo(self):
        """"""


TEST_TABLE = SymbolTable(
    {
        "ApacheThriftConfig": ApacheThriftConfiguration,
        "Struct": Struct,
        "StructWithDeps": StructWithDeps,
        "PublishConfig": PublishConfiguration,
        "Target": Target,
    }
)


class GraphTestBase(unittest.TestCase, SchedulerTestBase):
    def create(self, build_patterns=None, parser=None) -> SchedulerSession:
        address_mapper = AddressMapper(
            parser=parser, prelude_glob_patterns=(), build_patterns=build_patterns
        )

        @rule
        def symbol_table_singleton() -> SymbolTable:
            return TEST_TABLE

        rules = create_fs_rules() + create_graph_rules(address_mapper) + [symbol_table_singleton]
        project_tree = self.mk_fs_tree(os.path.join(os.path.dirname(__file__), "examples"))
        return cast(SchedulerSession, self.mk_scheduler(rules=rules, project_tree=project_tree))

    def create_json(self) -> SchedulerSession:
        return self.create(build_patterns=("*.BUILD.json",), parser=JsonParser(TEST_TABLE))

    def _populate(
        self, scheduler: SchedulerSession, address: Address,
    ) -> Tuple[ExecutionRequest, State]:
        """Perform an ExecutionRequest to parse the given Address into a Struct."""
        request = scheduler.execution_request([HydratedStruct], [address])
        returns, throws = scheduler.execute(request)
        if returns:
            state = returns[0][1]
        else:
            state = throws[0][1]
        return request, state

    def resolve_failure(self, scheduler: SchedulerSession, address: Address):
        _, state = self._populate(scheduler, address)
        assert isinstance(state, Throw)
        return state.exc

    def resolve(self, scheduler: SchedulerSession, address: Address):
        _, state = self._populate(scheduler, address)
        assert isinstance(state, Return)
        return state.value.value


class InlinedGraphTest(GraphTestBase):
    def do_test_codegen_simple(self, scheduler):
        def address(name: str) -> Address:
            return Address(spec_path="graph_test", target_name=name)

        resolved_java1 = self.resolve(scheduler, address("java1"))

        nonstrict = ApacheThriftConfiguration(
            type_alias="ApacheThriftConfig",
            address=address("nonstrict"),
            version="0.10.0",
            strict=False,
            lang="java",
        )
        public = Struct(
            type_alias="Struct",
            address=address("public"),
            url="https://oss.sonatype.org/#stagingRepositories",
        )
        thrift1 = Target(address=address("thrift1"))
        thrift2 = Target(address=address("thrift2"), dependencies=[thrift1])
        expected_java1 = Target(
            address=address("java1"),
            configurations=[
                PublishConfiguration(type_alias="PublishConfig", default_repo=public),
                nonstrict,
                ApacheThriftConfiguration(
                    type_alias="ApacheThriftConfig",
                    version="0.10.0",
                    strict=True,
                    dependencies=[address("thrift2")],
                    lang="java",
                ),
            ],
            dependencies=[thrift2],
            type_alias="Target",
        )

        self.assertEqual(expected_java1.configurations, resolved_java1.configurations)

    def test_json(self) -> None:
        scheduler = self.create_json()
        self.do_test_codegen_simple(scheduler)

    def test_python(self) -> None:
        scheduler = self.create(
            build_patterns=("*.BUILD.python",), parser=PythonAssignmentsParser(TEST_TABLE)
        )
        self.do_test_codegen_simple(scheduler)

    def test_python_classic(self) -> None:
        scheduler = self.create(
            build_patterns=("*.BUILD",), parser=PythonCallbacksParser(TEST_TABLE)
        )
        self.do_test_codegen_simple(scheduler)

    def test_resolve_cache(self) -> None:
        scheduler = self.create_json()

        nonstrict_address = Address.parse("graph_test:nonstrict")
        nonstrict = self.resolve(scheduler, nonstrict_address)
        self.assertEqual(nonstrict, self.resolve(scheduler, nonstrict_address))

        # The already resolved `nonstrict` interior node should be re-used by `java1`.
        java1_address = Address.parse("graph_test:java1")
        java1 = self.resolve(scheduler, java1_address)
        self.assertEqual(nonstrict, java1.configurations[1])

        self.assertEqual(java1, self.resolve(scheduler, java1_address))

    def do_test_trace_message(self, scheduler, parsed_address, expected_regex=None) -> None:
        # Confirm that the root failed, and that a cycle occurred deeper in the graph.
        request, state = self._populate(scheduler, parsed_address)
        self.assertEqual(type(state), Throw)
        with self.assertRaises(ExecutionError) as cm:
            scheduler._raise_on_error([state])
        trace_message = str(cm.exception)

        if expected_regex:
            print(trace_message)
            self.assertRegex(trace_message, expected_regex)

    def do_test_cycle(self, address_str: str, cyclic_address_str: str) -> None:
        scheduler = self.create_json()
        parsed_address = Address.parse(address_str)
        self.do_test_trace_message(
            scheduler,
            parsed_address,
            f"(?ms)Dependency graph contained a cycle:.*{cyclic_address_str}.* <-.*{cyclic_address_str}.* <-",
        )

    def test_cycle_self(self) -> None:
        self.do_test_cycle("graph_test:self_cycle", "graph_test:self_cycle")

    def test_cycle_direct(self) -> None:
        self.do_test_cycle("graph_test:direct_cycle", "graph_test:direct_cycle")

    def test_cycle_indirect(self) -> None:
        self.do_test_cycle("graph_test:indirect_cycle", "graph_test:one")

    def test_type_mismatch_error(self) -> None:
        scheduler = self.create_json()
        mismatch = Address.parse("graph_test:type_mismatch")
        self.assert_resolve_failure_type(ResolvedTypeMismatchError, mismatch, scheduler)
        self.do_test_trace_message(scheduler, mismatch)

    def test_not_found_but_family_exists(self) -> None:
        scheduler = self.create_json()
        dne = Address.parse("graph_test:this_addressable_does_not_exist")
        self.assert_resolve_failure_type(ResolveError, dne, scheduler)
        self.do_test_trace_message(scheduler, dne)

    def test_not_found_and_family_does_not_exist(self) -> None:
        scheduler = self.create_json()
        dne = Address.parse("this/dir/does/not/exist")
        self.assert_resolve_failure_type(ResolveError, dne, scheduler)
        self.do_test_trace_message(scheduler, dne)

    def assert_resolve_failure_type(
        self, expected_type: Type[Exception], mismatch: Address, scheduler: SchedulerSession
    ) -> None:
        failure = self.resolve_failure(scheduler, mismatch)
        self.assertEqual(
            type(failure),
            expected_type,
            f"type was not {expected_type.__name__}. Instead was {type(failure).__name__}, {failure!r}",
        )


class PreludeParsingTest(unittest.TestCase):
    def test_good_prelude(self) -> None:
        address_mapper = unittest.mock.Mock()
        address_mapper.prelude_glob_patterns = ("prelude",)

        symbols = run_rule(
            evaluate_preludes,
            rule_args=[address_mapper,],
            mock_gets=[
                MockGet(
                    product_type=Snapshot,
                    subject_type=PathGlobs,
                    mock=lambda _: Snapshot(Digest("abc", 10), ("/dev/null/prelude",), ()),
                ),
                MockGet(
                    product_type=FilesContent,
                    subject_type=Digest,
                    mock=lambda _: FilesContent(
                        [FileContent(path="/dev/null/prelude", content=b"def foo(): return 1")]
                    ),
                ),
            ],
        )
        assert symbols.symbols["foo"]() == 1

    def test_syntax_error(self) -> None:
        address_mapper = unittest.mock.Mock()
        address_mapper.prelude_glob_patterns = ("prelude",)

        with self.assertRaisesRegex(
            Exception, "Error parsing prelude file /dev/null/prelude: name 'blah' is not defined"
        ):
            run_rule(
                evaluate_preludes,
                rule_args=[address_mapper,],
                mock_gets=[
                    MockGet(
                        product_type=Snapshot,
                        subject_type=PathGlobs,
                        mock=lambda _: Snapshot(Digest("abc", 10), ("/dev/null/prelude",), ()),
                    ),
                    MockGet(
                        product_type=FilesContent,
                        subject_type=Digest,
                        mock=lambda _: FilesContent(
                            [FileContent(path="/dev/null/prelude", content=b"blah")]
                        ),
                    ),
                ],
            )

    def test_illegal_import(self) -> None:
        prelude = dedent(
            """\
            import os
            def make_target():
                python_library()
            """
        ).encode()

        address_mapper = unittest.mock.Mock()
        address_mapper.prelude_glob_patterns = ("prelude",)

        with self.assertRaisesRegex(
            Exception, "Import used in /dev/null/prelude at line 1\\. Import statements are banned"
        ):
            run_rule(
                evaluate_preludes,
                rule_args=[address_mapper,],
                mock_gets=[
                    MockGet(
                        product_type=Snapshot,
                        subject_type=PathGlobs,
                        mock=lambda _: Snapshot(Digest("abc", 10), ("/dev/null/prelude",), ()),
                    ),
                    MockGet(
                        product_type=FilesContent,
                        subject_type=Digest,
                        mock=lambda _: FilesContent(
                            [FileContent(path="/dev/null/prelude", content=prelude)]
                        ),
                    ),
                ],
            )
