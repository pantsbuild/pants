# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""An 80% re-implementation of buildozer's CLI.

Many of the below operations are ripped directly from the "Edit commands" section of the buildozer
README: https://github.com/bazelbuild/buildtools/blob/master/buildozer/README.md#edit-commands.

Note that the terminology "rule" in the above link has been replaced with "target" in this file.
"""

import ast
from abc import ABC, abstractmethod, abstractproperty
from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, List, Iterable, Optional, Tuple, Union, Type

import libcst as cst

from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoryToMaterialize, Workspace, FileContent, InputFilesContent
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.objects import HashableDict, union
from pants.engine.rules import UnionMembership, UnionRule, goal_rule, rule
from pants.engine.selectors import Get
from pants.rules.build_file_manipulation.interactive_console import InteractiveConsole
from pants.rules.build_file_manipulation.match_cst_nodes import BuildFileObjectMatcher, CSTBuildFileTransformer, FullyMappedAddressTable, FullyMapAddressesRequest
from pants.util.collections import assert_zero_or_one_kwarg
from pants.util.memo import memoized_method, memoized_property
from pants.util.strutil import safe_shlex_split


@union
class BuildozerCommand(CSTBuildFileTransformer, ABC):
    @classmethod
    @abstractproperty
    def buildozer_command_name(cls) -> str:
        ...

    @classmethod
    @abstractmethod
    def parse_from_args(cls, *args) -> 'BuildozerCommand':
        ...


class NamedAttributeModifier(ABC):
    @abstractmethod
    def modify_attribute(
        self,
        bfom: BuildFileObjectMatcher,
        updated_node: cst.Call,
        matching_arg: cst.Arg,
    ) -> Optional[cst.Call]:
        ...

    def do_leave_call(
        self,
        bfom: BuildFileObjectMatcher,
        original_node: cst.Call,
        updated_node: cst.Call,
    ) -> Union[cst.Call, cst.RemovalSentinel]:
        matching_arg = assert_zero_or_one_kwarg(
            arg for arg in updated_node.args
            if arg.keyword.value == self.attr
        )
        if not matching_arg:
            return updated_node

        result = self.modify_attribute(bfom, updated_node, matching_arg)
        if result is None:
            return cst.RemovalSentinel.REMOVE
        return result


@dataclass(frozen=True)
class AddValuesToList(NamedAttributeModifier, BuildozerCommand):
    attr: str
    values: Tuple[str, ...]

    buildozer_command_name = 'add'

    @classmethod
    def parse_from_args(cls, attr, *values):
        return cls(attr=attr, values=tuple(values))

    _known_collection_types = (cst.List, cst.Set)

    def modify_attribute(
        self,
        bfom: BuildFileObjectMatcher,
        updated_node: cst.Call,
        matching_arg: cst.Arg,
    ) -> Optional[cst.Call]:
        collection_type = type(matching_arg.value)

        if collection_type not in self._known_collection_types:
            raise TypeError(
                f"add-values-to-list operator {self} used on non-list (or set) argument {matching_arg.value}!")

        all_new_elements = [
            *matching_arg.value.elements,
            # Convert the string values into libCST's representation of them as elements in a list
            # literal.
            *(cst.Element(cst.SimpleString(f'"{val}"')) for val in self.values),
        ]
        updated_arg = matching_arg.with_changes(
            value=collection_type(all_new_elements))

        # The above mutations of `matching_arg` should have correctly "updated" this parent node.
        return updated_node.deep_replace(matching_arg, updated_arg)


class CommentAttachment(Enum):
    """Where comments are to be attached to: the target, an attribute, or an element of a list
    attribute."""
    Target = 'target'
    Attribute = 'attribute'
    Value = 'value'


@dataclass(frozen=True)
class CommentLocation:
    attachment: CommentAttachment
    attr_name: Optional[str]
    attr_specific_value_in_list: Optional[str]

    @classmethod
    def from_attr_and_value(self, attr: Optional[str], value: Optional[str]) -> 'CommentLocation':
        attachment = CommentAttachment.Target
        attr_name: Optional[str] = None
        attr_specific_value_in_list: Optional[str] = None

        if attr:
            attr_name = attr
            if value:
                attr_specific_value_in_list = value
                attachment = CommentAttachment.Value
            else:
                attachment = CommentAttachment.Attribute
        return cls(attachment=attachment,
                   attr_name=attr_name,
                   attr_specific_value_in_list=attr_specific_value_in_list)


class CommentInsertionLocation(ABC):
    @memoized_method
    def determine_location(self) -> CommentLocation:
        return CommentLocation.from_attr_and_value(
            attr=self.attr,
            value=self.value)


@dataclass(frozen=True)
class Comment(BuildozerCommand, CommentInsertionLocation):
    comment: str
    attr: Optional[str]
    value: Optional[str]

    buildozer_command_name = 'comment'


@dataclass(frozen=True)
class PrintComment(BuildozerCommand, CommentInsertionLocation):
    attr: Optional[str]
    value: Optional[str]

    buildozer_command_name = 'print_comment'


@dataclass(frozen=True)
class RemoveComment(BuildozerCommand, CommentInsertionLocation):
    attr: Optional[str]
    value: Optional[str]

    buildozer_command_name = 'remove_comment'


@dataclass(frozen=True)
class DeleteTarget(BuildozerCommand):
    buildozer_command_name = 'delete'


@dataclass(frozen=True)
class MaybeWildcard:
    """A wrapper for string inputs which may interpreted with string wildcards.

    These wildcards are used to match against attribute values to move, copy, or remove.

    NB: Currently, the only wildcard interpreted is '*', that is, a string containing only the
    single asterisk character.
    """
    glob_or_string: str

    def __post_init__(self) -> None:
        if ('*' in self.glob_or_string) and self.glob_or_string != '*':
            raise TypeError(f'maybe wildcard input {self.glob_or_string} must contain zero '
                            'asterisks, or be composed of only a single asterisk!')


@dataclass(frozen=True)
class MoveValues(BuildozerCommand):
    old_attr: str
    new_attr: str
    values: Tuple[MaybeWildcard, ...]

    buildozer_command_name = 'move'


class Preposition(Enum):
    before = 'before'
    after = 'after'


@dataclass(frozen=True)
class NewTargetPreposition:
    preposition: Preposition
    relative_target_name: Address


@dataclass(frozen=True)
class NewTarget(BuildozerCommand):
    type_alias: str
    name: str
    preposition: Optional[NewTargetPreposition]

    buildozer_command_name = 'new'


class Printable(ABC):
    @abstractmethod
    def lines_to_print(self) -> List[str]:
        ...


@dataclass(frozen=True)
class PrintValue(BuildozerCommand, Printable):
    attrs: Tuple[str, ...]

    buildozer_command_name = 'print'

    @classmethod
    def parse_from_args(cls, *attrs):
        return cls(tuple(attrs))

    @memoized_property
    def _attrs_set(self) -> FrozenSet[str]:
        return frozenset(self.attrs)

    @memoized_property
    def _printable_lines(self) -> List[str]:
        return []

    def lines_to_print(self) -> List[str]:
        return self._printable_lines

    def do_visit_call(self, bfom: BuildFileObjectMatcher, node: cst.Call) -> bool:
        relevant_args = [
            arg for arg in node.args if arg.keyword.value in self._attrs_set
        ]
        for arg in relevant_args:
            if not isinstance(arg.value, cst.SimpleString):
                raise TypeError(
                    f'print visitor {self} encountered a non-string-valued attribute {arg}!')
            self._printable_lines.append(ast.literal_eval(arg.value.value))
        return True


@dataclass(frozen=True)
class RemoveAttribute(BuildozerCommand):
    attr: str

    # This is a different name than the monolithic `remove` command in buildozer which covers both
    # RemoveAttribute and RemoveValues.
    buildozer_command_name = 'remove_attr'


@dataclass(frozen=True)
class RemoveValues(BuildozerCommand):
    attr: MaybeWildcard
    values: Tuple[str, ...]

    buildozer_command_name = 'remove_values'


@dataclass(frozen=True)
class RenameAttribute(BuildozerCommand):
    old_attr: str
    new_attr: str

    buildozer_command_name = 'rename'


@dataclass(frozen=True)
class ReplaceValue(BuildozerCommand):
    attr: MaybeWildcard
    old_value: str
    new_value: str

    buildozer_command_name = 'replace'


@dataclass(frozen=True)
class SubstituteValuesViaRegexp(BuildozerCommand):
    attr: MaybeWildcard
    old_regexp: str
    new_template: str

    buildozer_command_name = 'substitute'


@dataclass(frozen=True)
class ResetAttributeValue(BuildozerCommand):
    attr: str
    values: Tuple[str, ...]

    buildozer_command_name = 'set'


@dataclass(frozen=True)
class SetAttributeIfAbsent(BuildozerCommand):
    attr: str
    values: Tuple[str, ...]

    buildozer_command_name = 'set_if_absent'


@dataclass(frozen=True)
class SetTargetType(BuildozerCommand):
    new_type_alias: str

    # This is different from buildozer's "set kind", to conform to pants naming conventions.
    buildozer_command_name = 'set_type_alias'


@dataclass(frozen=True)
class CopyAttributeValue(BuildozerCommand):
    attr: str
    from_target: str

    buildozer_command_name = 'copy'


@dataclass(frozen=True)
class CopyAttributeIfAbsent(BuildozerCommand):
    attr: str
    from_target: str

    buildozer_command_name = 'copy_no_overwrite'


class DictValues(HashableDict[str, Union[str, Tuple[str, ...]]]):
    """This represents the type of data that can be added to a dict-valued attribute."""


@dataclass(frozen=True)
class SetDictValuesIfAbsent(BuildozerCommand):
    attr: str
    new_values: DictValues

    buildozer_command_name = 'dict_add'


@dataclass(frozen=True)
class ResetDictValues(BuildozerCommand):
    attr: str
    new_values: DictValues

    buildozer_command_name = 'dict_set'


@dataclass(frozen=True)
class DeleteDictKeys(BuildozerCommand):
    attr: str
    keys: Tuple[str, ...]

    buildozer_command_name = 'dict_delete'


@dataclass(frozen=True)
class AddValuesToDictValueList(BuildozerCommand):
    attr: str
    key: str
    values: Tuple[str, ...]

    buildozer_command_name = 'dict_list_add'


@dataclass(frozen=True)
class KnownBuildozerCommands:
    mapping: HashableDict[str, Type]

    def get(self, name: str) -> Type:
        if name not in self.mapping.as_dict:
            raise TypeError(f'could not find buildozer command matching name {name}!')
        return self.mapping.as_dict[name]


@rule
def known_buildozer_commands(union_membership: UnionMembership) -> KnownBuildozerCommands:
    return KnownBuildozerCommands(HashableDict[str, Type]({
        union_member.buildozer_command_name: union_member
        for union_member in union_membership.union_rules[BuildozerCommand]
    }))


class BuildozerOptions(LineOriented, GoalSubsystem):
    """???"""
    name = 'buildozer2'

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register('--args', type=list, default=[], fingerprint=True,
                 help='The arguments to pass to buildozer. With some exceptions, the commands from '
                      'https://github.com/bazelbuild/buildtools/blob/master/buildozer/README.md#edit-commands'
                      'can be used directly.')

    def parse_buildozer_expressions(
        self,
        known_commands: KnownBuildozerCommands,
    ) -> List[BuildozerCommand]:
        command_instances = []
        for arg_string in self.values.args:
            argv = safe_shlex_split(arg_string)
            assert argv, f'received blank string for buildozer argument'
            name = argv[0]
            rest = argv[1:]
            command_cls = known_commands.get(name)
            command_instances.append(command_cls.parse_from_args(*rest))
        return command_instances


class Buildozer(Goal):
    subsystem_cls = BuildozerOptions


@goal_rule
async def do_buildozer(
    console: Console,
    options: BuildozerOptions,
    addresses: Addresses,
    known_buildozer_commands: KnownBuildozerCommands,
    workspace: Workspace,
) -> Buildozer:
    transformers = options.parse_buildozer_expressions(known_buildozer_commands)
    table = await Get[FullyMappedAddressTable](FullyMapAddressesRequest(
        addresses=addresses, transformers=tuple(transformers),
    ))

    for t in transformers:
        if isinstance(t, Printable):
            lines = t.lines_to_print()
            console.print_stdout('\n'.join(lines))

    # py_console = InteractiveConsole()
    # py_console.interact(locals=locals())

    transformed_build_files = table.mapping.keys()
    modified_files_digest = await Get[Digest](InputFilesContent(tuple([
        FileContent(
            path=str(transformed_bf.build_file_relpath),
            content=transformed_bf.maybe_modified_source.code.encode(),
            is_executable=False)
        for transformed_bf in transformed_build_files
    ])))
    workspace.materialize_directory(DirectoryToMaterialize(directory_digest=modified_files_digest))

    joined_paths = '\n'.join(str(parsed_bf.build_file_relpath)
                             for parsed_bf in transformed_build_files)
    console.print_stdout(f'fixed {len(transformed_build_files)} files:\n{joined_paths}')

    return Buildozer(exit_code=0)


def rules():
    return [
        known_buildozer_commands,
        UnionRule(BuildozerCommand, AddValuesToList),
        UnionRule(BuildozerCommand, Comment),
        UnionRule(BuildozerCommand, PrintComment),
        UnionRule(BuildozerCommand, RemoveComment),
        UnionRule(BuildozerCommand, DeleteTarget),
        UnionRule(BuildozerCommand, MoveValues),
        UnionRule(BuildozerCommand, NewTarget),
        UnionRule(BuildozerCommand, PrintValue),
        UnionRule(BuildozerCommand, RemoveAttribute),
        UnionRule(BuildozerCommand, RemoveValues),
        UnionRule(BuildozerCommand, RenameAttribute),
        UnionRule(BuildozerCommand, ReplaceValue),
        UnionRule(BuildozerCommand, SubstituteValuesViaRegexp),
        UnionRule(BuildozerCommand, ResetAttributeValue),
        UnionRule(BuildozerCommand, SetAttributeIfAbsent),
        UnionRule(BuildozerCommand, SetTargetType),
        UnionRule(BuildozerCommand, CopyAttributeValue),
        UnionRule(BuildozerCommand, CopyAttributeIfAbsent),
        UnionRule(BuildozerCommand, SetDictValuesIfAbsent),
        UnionRule(BuildozerCommand, ResetDictValues),
        UnionRule(BuildozerCommand, DeleteDictKeys),
        UnionRule(BuildozerCommand, AddValuesToDictValueList),
        do_buildozer,
    ]
