# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
import os
from abc import ABC
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Dict, Iterator, Iterable, List, Optional, Union, Tuple

import libcst as cst

from pants.base.project_tree import Dir
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.addressable import Addresses, BuildFileAddresses
from pants.engine.console import Console
from pants.engine.fs import Digest, FileContent, FilesContent, PathGlobs, Snapshot
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.mapper import AddressFamily
from pants.engine.objects import Collection, HashableDict
from pants.engine.parser import SymbolTable
from pants.engine.rules import RootRule, goal_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.build_file_manipulation.interactive_console import InteractiveConsole
from pants.util.collections import assert_zero_or_one
from pants.util.memo import memoized_property
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class BuildFileToParse:
    relpath: Path
    contents: str

    @classmethod
    def from_file_content(cls, file_content: FileContent) -> "BuildFileToParse":
        relpath = Path(file_content.path)
        source_string = file_content.content.decode()
        return cls(relpath, source_string)


@dataclass(frozen=True)
class ParsedBuildFile:
    build_file_relpath: Path
    parsed: cst.Module


@rule
def parse_build_file(file_to_parse: BuildFileToParse) -> ParsedBuildFile:
    parsed = cst.parse_module(file_to_parse.contents, cst.PartialParserConfig(python_version="3.7"))
    return ParsedBuildFile(build_file_relpath=file_to_parse.relpath, parsed=parsed)


@dataclass(frozen=True)
class ParsedBuildFileAddresses:
    mapping: HashableDict[ParsedBuildFile, Addresses]


@rule
async def build_files_for(addresses: Addresses) -> ParsedBuildFileAddresses:
    build_file_addresses = await Get[BuildFileAddresses](Addresses, addresses)
    snapshot = await Get[Snapshot](PathGlobs([bfa.rel_path for bfa in build_file_addresses]))
    all_file_contents = await Get[FilesContent](Digest, snapshot.directory_digest)

    files_to_parse = [BuildFileToParse.from_file_content(content) for content in all_file_contents]
    build_file_to_address_mapping = {
        build_file_to_parse: Addresses(
            bfa.to_address()
            for bfa in build_file_addresses
            if Path(bfa.rel_path) == build_file_to_parse.relpath
        )
        for build_file_to_parse in files_to_parse
    }

    parsed_build_files = await MultiGet(
        Get[ParsedBuildFile](BuildFileToParse, to_parse)
        for to_parse in build_file_to_address_mapping.keys()
    )

    # Replace the un-parsed BUILD files with parsed ones in the result!
    result = dict(zip(parsed_build_files, build_file_to_address_mapping.values()))

    return ParsedBuildFileAddresses(HashableDict[ParsedBuildFile, Addresses](result))


@dataclass(frozen=True)
class MatchedObject:
    addressable_object: TargetAdaptor


@rule
async def match_address_to_object(address: Address) -> MatchedObject:
    family = await Get[AddressFamily](Address, address)
    assert (
        family.namespace == address.spec_path
    ), f"namespace {family.namespace} should equal spec path {address.spec_path}"

    path, obj = family.objects_by_name[address.target_name]

    bfa = await Get[BuildFileAddress](Address, address)
    assert (
        path == bfa.rel_path
    ), f"path {path} from address family {family} did not match BUILD file address {bfa}"
    assert isinstance(obj, TargetAdaptor), f"object should be TargetAdaptor: was {obj}"
    return MatchedObject(obj)


@dataclass(frozen=True)
class MatchedBuildFileObjects:
    parsed_build_file: ParsedBuildFile
    matched_objects: HashableDict[Address, TargetAdaptor]
    transformers: Tuple['CSTBuildFileTransformer', ...]

    def into_matchers(self) -> List['BuildFileObjectMatcher']:
        return [
            BuildFileObjectMatcher(address=address, adaptor=adaptor)
            for address, adaptor in self.matched_objects.items()
        ]


@dataclass(frozen=True)
class CSTCallMatcher:
    call: cst.Call
    type_alias: str
    object_name: Optional[str]

    @classmethod
    def from_call(cls, call: cst.Call) -> 'CSTCallMatcher':
        type_alias = call.func.value
        object_name_literal = assert_zero_or_one(
            (arg for arg in call.args if arg.keyword.value == "name"),
            error_message="these are kwargs",
        )
        # NB: libCST will keep a string form of the exact string as in the BUILD file, including the
        # surrounding quotes. So we eval it here to get the name, which is all we're interested in.
        object_name = ast.literal_eval(object_name_literal.value.value)
        return cls(
            call=call,
            type_alias=type_alias,
            object_name=object_name,
        )

    def __post_init__(self) -> None:
        assert self.type_alias != '', f'A type alias cannot be an empty string!! Call was: {self}.'
        assert self.object_name != '', f'A target name cannot be an empty string!! Call was: {self}.'

    def matches(self, bfom: 'BuildFileObjectMatcher') -> bool:
        if self.type_alias != bfom.type_alias:
            return False
        if self.object_name:
            return self.object_name == bfom.object_name
        return bfom.object_name_may_be_default


@dataclass(frozen=True)
class MatchedCstNodes:
    mapping: HashableDict[Address, CSTCallMatcher]
    possibly_new_parsed_module: cst.Module


@dataclass(frozen=True)
class BuildFileObjectMatcher:
    """A set of information about a target used to locate it within a libCST tree."""
    address: Address
    adaptor: TargetAdaptor

    @property
    def type_alias(self) -> str:
        return self.adaptor.type_alias

    @property
    def object_name(self) -> str:
        return self.address.target_name

    @memoized_property
    def object_name_may_be_default(self) -> bool:
        """When a target's name matches the name of its containing directory, it may be found in a
        BUILD file without any 'name' kwarg. If so, it would be the only such target in that
        directory."""
        return self.address.target_name == os.path.basename(self.address.spec_path)


class CSTBuildFileTransformer(ABC):
    """These are analogies to the visit_Call and leave_Call methods.

    This is in a separate class from cst.CSTTransformer to avoid boilerplate.
    """

    def do_visit_call(self, bfom: BuildFileObjectMatcher, call: cst.Call) -> bool:
        return True

    def do_leave_call(
        self,
        bfom: BuildFileObjectMatcher,
        original_node: cst.Call,
        updated_node: cst.Call,
    ) -> Union[cst.Call, cst.RemovalSentinel]:
        return updated_node


class CSTCallBuildFileAddressGatherer(CSTBuildFileTransformer):
    def __init__(self) -> None:
        self._found_addressable_nodes: Dict[Address, cst.Call] = {}

    def do_leave_call(
        self,
        bfom: BuildFileObjectMatcher,
        original_node: cst.Call,
        updated_node: cst.Call,
    ) -> Union[cst.Call, cst.RemovalSentinel]:
        address = bfom.address
        assert (
            address not in self._found_addressable_nodes
        ), f"did not expect to see the same address twice: {self._found_addressable_nodes[address]} and {call}"
        self._found_addressable_nodes[address] = updated_node
        return updated_node

    @property
    def found_addressable_nodes(self) -> Dict[Address, cst.Call]:
        return self._found_addressable_nodes


class BuildFileBatchedCSTTransformer(cst.CSTTransformer):
    def __init__(
        self,
        matchers: Iterable[BuildFileObjectMatcher],
        transformers: Iterable[CSTBuildFileTransformer],
    ) -> None:
        self._matchers: List[BuildFileObjectMatcher] = list(matchers)
        self._transformers: List[CSTBuildFileTransformer] = list(transformers)

    def _any_match(self, call_matcher: CSTCallMatcher) -> Optional[BuildFileObjectMatcher]:
        for m in self._matchers:
            if call_matcher.matches(m):
                return m
        return None

    def visit_Call(self, call: cst.Call) -> bool:
        call_matcher = CSTCallMatcher.from_call(call)
        m = self._any_match(call_matcher)
        if m:
            any_said_yes = False
            for t in self._transformers:
                if t.do_visit_call(m, call):
                    any_said_yes = True
            return any_said_yes
        return True

    def leave_Call(
        self,
        original_node: cst.Call,
        updated_node: cst.Call,
    ) -> Union[cst.Call, cst.RemovalSentinel]:
        call_matcher = CSTCallMatcher.from_call(original_node)
        m = self._any_match(call_matcher)
        if m:
            for t in self._transformers:
                new_call = t.do_leave_call(m, original_node, updated_node)
                if isinstance(new_call, cst.RemovalSentinel):
                    return new_call
                updated_node = new_call
        return updated_node


@rule
def match_address_to_cst_node(matched_bfo: MatchedBuildFileObjects) -> MatchedCstNodes:
    # Create "matcher" objects which are used to locate the corresponding libCST node for each
    # target.
    matchers = matched_bfo.into_matchers()
    # Create the libCST visitor.
    address_gatherer = CSTCallBuildFileAddressGatherer()
    build_file_visitor = BuildFileBatchedCSTTransformer(
        matchers=matchers,
        transformers=[
            *matched_bfo.transformers,
            # NB: It's important that the address gatherer go after any potential CST modifications
            # from other transformers, so that the FullyMappedAddress can have the fully updated
            # `node` value.
            address_gatherer,
        ],
    )
    # Invoke the visitor.
    possibly_modified_bfo_module = matched_bfo.parsed_build_file.parsed.visit(build_file_visitor)
    assert isinstance(possibly_modified_bfo_module, cst.Module), f'expected result of visiting module to return module, was: {possibly_modified_bfo_module}'

    # Assert that all addresses that were searched for were found.
    # FIXME: this currently assumes every target we'd want to affect has a specific name and isn't
    # generated by a function or macro!!!
    original_addresses = set(matched_bfo.matched_objects.keys())
    found_addresses = set(address_gatherer.found_addressable_nodes.keys())
    assert (
        original_addresses == found_addresses
    ), f"searched addresses {original_addresses} did not match found addresses {found_addresses} parsed from BUILD file at {matched_bfo.parsed_build_file.build_file_relpath}"

    return MatchedCstNodes(
        mapping=HashableDict(address_gatherer.found_addressable_nodes),
        possibly_new_parsed_module=possibly_modified_bfo_module,
    )


@dataclass(frozen=True)
class FullyMappedAddress:
    address: Address
    adaptor: TargetAdaptor
    node: cst.CSTNode


class FullyMappedAddresses(Collection[FullyMappedAddress]):
    pass


@dataclass(frozen=True)
class TransformedBuildFile:
    build_file_relpath: Path
    maybe_modified_source: cst.Module


@dataclass(frozen=True)
class FullyMappedAddressTable:
    mapping: HashableDict[TransformedBuildFile, FullyMappedAddresses]


@dataclass(frozen=True)
class FullyMapAddressesRequest:
    addresses: Addresses
    transformers: Tuple[CSTBuildFileTransformer, ...] = ()


@rule
async def fully_map_addresses(req: FullyMapAddressesRequest) -> FullyMappedAddressTable:
    addresses = req.addresses

    # Parse all BUILD files corresponding to `addresses` with libCST!
    parsed_bfas = await Get[ParsedBuildFileAddresses](Addresses, addresses)

    # Match each Address to the `TargetAdaptor` it corresponds to. Technically, it's `Serializable`,
    # but they're all `TargetAdaptor`s in practice right now.
    matching_addresses_to_objects: Dict[Address, MatchedObject] = dict(
        zip(
            addresses, await MultiGet(Get[MatchedObject](Address, address) for address in addresses)
        )
    )

    # Accumulate all Addresses with their matched TargetAdaptors into a dict, and group by the
    # libCST-parsed BUILD file each address was declared in.
    matched_bfos = [
        MatchedBuildFileObjects(
            parsed_build_file=parsed_bf,
            matched_objects=HashableDict(
                {addr: matching_addresses_to_objects[addr].addressable_object for addr in addresses}
            ),
            transformers=req.transformers,
        )
        for parsed_bf, addresses in parsed_bfas.mapping.items()
    ]

    # Scan the CST of each BUILD file for the objects matching the given addresses.
    matched_cst_nodes: Dict[MatchedBuildFileObjects, MatchedCstNodes] = dict(
        zip(
            matched_bfos,
            await MultiGet(
                Get[MatchedCstNodes](MatchedBuildFileObjects, objs) for objs in matched_bfos
            ),
        )
    )

    # Map each parsed BUILD file to a list of records coagulating all the information we've just
    # found about out each address.
    fully_mapped_addresses = {
        TransformedBuildFile(
            build_file_relpath=obj.parsed_build_file.build_file_relpath,
            maybe_modified_source=matched_nodes.possibly_new_parsed_module,
        ): FullyMappedAddresses(
            FullyMappedAddress(
                address=addr, adaptor=adaptor, node=matched_nodes.mapping.as_dict[addr],
            )
            for addr, adaptor in obj.matched_objects.items()
        )
        for obj, matched_nodes in matched_cst_nodes.items()
    }

    return FullyMappedAddressTable(
        HashableDict[ParsedBuildFile, FullyMappedAddresses](fully_mapped_addresses)
    )


class ShowBuildFilesOptions(LineOriented, GoalSubsystem):
    """Drop into a REPL which allows viewing modifying BUILD file target definitions."""

    name = "show-build-files"


class ShowBuildFiles(Goal):
    subsystem_cls = ShowBuildFilesOptions


@goal_rule
async def show_build_files(
    console: Console, options: ShowBuildFilesOptions, addresses: Addresses,
) -> ShowBuildFiles:
    table = await Get[FullyMappedAddressTable](FullyMapAddressesRequest(addresses))
    py_console = InteractiveConsole()
    py_console.interact(locals=locals())

    return ShowBuildFiles(exit_code=0)


def rules():
    return [
        RootRule(BuildFileToParse),
        parse_build_file,
        build_files_for,
        match_address_to_object,
        RootRule(MatchedBuildFileObjects),
        match_address_to_cst_node,
        RootRule(FullyMapAddressesRequest),
        fully_map_addresses,
        show_build_files,
    ]
