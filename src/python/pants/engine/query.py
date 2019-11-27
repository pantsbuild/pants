# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Tuple, Type, TypeVar

from pants.build_graph.address import Address
from pants.engine.collection import Collection
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.scm.git import Git
from pants.scm.subsystems.changed import (
    ChangedFiles,
    ChangedFilesRequest,
    ChangedOptions,
    ChangedAddresses,
    ChangedRequest,
    DependeesOption,
)
from pants.util.meta import classproperty
from pants.util.strutil import safe_shlex_split


@union
class QueryComponent(ABC):

    @classproperty
    @abstractmethod
    def function_name(cls):
        """The initial argument of a shlexed query expression.

        If the user provides --query='<name> <args...>' on the command line, and `<name>` matches this
        property, the .parse_from_args() method is invoked with `<args...>` (shlexed, so split by
        spaces).
        """

    @classmethod
    @abstractmethod
    def parse_from_args(cls, *args):
        """Create an instance of this class from variadic positional string arguments.

        This method should raise an error if the args are incorrect or invalid.
        """


class QueryAddresses(Collection[Address]):
    pass


@dataclass(frozen=True)
class OwnerOf(QueryComponent):
    files: Tuple[str]

    function_name = 'owner_of'

    @classmethod
    def parse_from_args(cls, *args):
        return cls(files=tuple([str(f) for f in args]))


@rule
async def owner_of_request(owner_of: OwnerOf) -> QueryAddresses:
    request = OwnersRequest(sources=owner_of.files, do_not_generate_subtargets=True)
    owners = await Get(Owners, OwnersRequest, request)
    return QueryAddresses(owners)


@dataclass(frozen=True)
class ChangesSince(QueryComponent):
    since: str
    dependees: DependeesOption

    function_name = 'since'

    @classmethod
    def parse_from_args(cls, since, dependees=DependeesOption.NONE):
        return cls(since=str(since),
                   dependees=DependeesOption(dependees))


@rule
async def since_request(
        git: Git,
        since: ChangesSince,
) -> QueryAddresses:
    changed_options = ChangedOptions(
        since=since.since,
        diffspec=None,
        dependees=since.dependees,
    )
    changed_files = await Get(ChangedFiles, ChangedFilesRequest(changed_options, git))
    changed = await Get(ChangedAddresses, ChangedRequest(
        sources=tuple(changed_files),
        dependees=changed_options.dependees,
        do_not_generate_subtargets=True,
    ))
    return QueryAddresses(changed)


@dataclass(frozen=True)
class ChangesForDiffspec(QueryComponent):
    diffspec: str
    dependees: DependeesOption

    function_name = 'changes_for_diffspec'

    @classmethod
    def parse_from_args(cls, diffspec, dependees=DependeesOption.NONE):
        return cls(diffspec=str(diffspec),
                   dependees=DependeesOption(dependees))


@rule
async def changes_for_diffspec_request(
        git: Git,
        changes_for_diffspec: ChangesForDiffspec,
) -> QueryAddresses:
    changed_options = ChangedOptions(
        since=None,
        diffspec=changes_for_diffspec.diffspec,
        dependees=changes_for_diffspec.dependees,
    )
    changed_files = await Get(ChangedFiles, ChangedFilesRequest(changed_options, git))
    changed = await Get(ChangedAddresses, ChangedRequest(
        sources=tuple(changed_files),
        dependees=changed_options.dependees,
        do_not_generate_subtargets=True,
    ))
    return QueryAddresses(changed)


_T = TypeVar('_T', bound=QueryComponent)


@dataclass(frozen=True)
class KnownQueryExpressions:
    components: Dict[str, Type[_T]]


@rule
def known_query_expressions(union_membership: UnionMembership) -> KnownQueryExpressions:
    return KnownQueryExpressions({
        union_member.function_name: union_member
        for union_member in union_membership[QueryComponent]
    })


@dataclass(frozen=True)
class QueryParseInput:
    expr: str


class QueryParseError(Exception): pass


@dataclass(frozen=True)
class QueryComponentWrapper:
    underlying: _T


@dataclass(frozen=True)
class ParsedPythonesqueFunctionCall:
    """Representation of a limited form of python named function calls."""
    function_name: str
    positional_args: Tuple[Any, ...]
    keyword_args: Dict[str, Any]


def _parse_python_arg(arg_value: ast.AST) -> Any:
    """Convert an AST node for the argument of a function call into its literal value."""
    return ast.literal_eval(arg_value)


def _parse_python_esque_function_call(expr: str) -> ParsedPythonesqueFunctionCall:
    """Parse a string into a description of a python function call expression."""
    try:
        query_expression = ast.parse(expr).body[0].value
    except Exception as e:
        raise QueryParseError(f'Error parsing query expression: {e}') from e

    if not isinstance(query_expression, ast.Call):
        type_name = type(query_expression).__name__
        raise QueryParseError(
            f'Query expression must be a single function call, but received {type_name}: '
            f'{ast.dump(query_expression)}.')

    func_expr = query_expression.func
    if not isinstance(func_expr, ast.Name):
        raise QueryParseError('Function call in query expression should just be a name, but '
                                                    f'received {type(func_expr).__name__}: {ast.dump(func_expr)}.')
    function_name = func_expr.id

    positional_args = [_parse_python_arg(x) for x in query_expression.args]
    keyword_args = {
        k.arg: _parse_python_arg(k.value)
        for k in query_expression.keywords
    }

    return ParsedPythonesqueFunctionCall(
        function_name=function_name,
        positional_args=positional_args,
        keyword_args=keyword_args,
    )


# TODO: allow returning an @union to avoid having to use this QueryComponentWrapper for type
# erasure.
@rule
def parse_query_expr(s: QueryParseInput, known: KnownQueryExpressions) -> QueryComponentWrapper:
    """Parse the input string and attempt to find a query function matching the function call.

    :return: A query component which can be resolved into `BuildFileAddresses` in the v2 engine.
    """
    try:
        parsed_function_call = _parse_python_esque_function_call(s.expr)
    except Exception as e:
        raise QueryParseError(f'Error parsing expression {s}: {e}.') from e

    name = parsed_function_call.function_name
    args = parsed_function_call.positional_args
    kwargs = parsed_function_call.keyword_args

    selected_function = known.components.get(name, None)
    if selected_function:
        return QueryComponentWrapper(selected_function.parse_from_args(*args, **kwargs))
    else:
        raise QueryParseError(
            f'Query function with name {name} not found (in expr {s})! '
            f'The known functions are: {known}.')


def rules():
    return [
        RootRule(OwnerOf),
        RootRule(ChangesSince),
        RootRule(QueryParseInput),
        RootRule(ChangesForDiffspec),
        known_query_expressions,
        UnionRule(QueryComponent, OwnerOf),
        UnionRule(QueryComponent, ChangesSince),
        UnionRule(QueryComponent, ChangesForDiffspec),
        owner_of_request,
        since_request,
        changes_for_diffspec_request,
        parse_query_expr,
    ]
