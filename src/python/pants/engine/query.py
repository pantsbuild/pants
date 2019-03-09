# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Generic, Tuple, Type, TypeVar

from pants.build_graph.address import Address
from pants.engine.addresses import Addresses
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.scm.subsystems.changed import ChangedOptions, ChangedAddresses, ChangedRequest, DependeesOption, UncachedScmWrapper
from pants.engine.legacy.graph import (
    HydratedTarget,
    HydratedTargets,
    TransitiveHydratedTargets,
)
from pants.util.enums import match
from pants.util.meta import classproperty
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


@union
class QueryParser(ABC):
    @classproperty
    @abstractmethod
    def function_name(cls):
        """The initial argument of a shlexed query expression.

        If the user provides --query='<name> <args...>' on the command line, and `<name>` matches
        this property, the .parse_from_args() method is invoked with `<args...>` (shlexed, so split
        by spaces).
        """

    @classmethod
    @abstractmethod
    def parse_from_args(cls, *args):
        """Create an instance of this class from variadic positional string arguments.

        This method should raise an error if the args are incorrect or invalid.
        """


@union
class Operator(ABC):
    """???"""

    def quick_hydrate_with_input(self, addresses: Addresses):
        """???/produce an object containing build file addresses which has a single rule graph path
        to IntermediateResults, AND which has:

        UnionRule(QueryOperation, <type of object returned by hydrate()>)
        """
        return None

    def as_hydration_request(self, hts: Tuple[HydratedTarget, ...]):
        """???"""
        return None


@dataclass(frozen=True)
class QueryAddresses:
    addresses: Addresses


@union
class QueryOperation:
    pass


@dataclass(frozen=True)
class HydratedOperator:
    operator: Operator


@dataclass(frozen=True)
class IntermediateResults:
    addresses: Addresses


@union
class OperatorRequest:
    pass


class TargetSelectionConjunction(Enum):
    union = "union"
    intersection = "intersection"

    def get_operator(self, addresses: Addresses) -> Operator:
        return match(
            self,
            {
                self.union: lambda: UnionOperator(addresses),
                self.intersection: lambda: IntersectionOperator(addresses),
            },
        )()


@dataclass(frozen=True)
class OwnerOf(QueryParser):
    files: Tuple[str, ...]
    conjunction: TargetSelectionConjunction

    function_name = "owner_of"

    @classmethod
    def parse_from_args(cls, *args, conjunction=TargetSelectionConjunction.union):
        return cls(
            files=tuple([str(f) for f in args]), conjunction=TargetSelectionConjunction(conjunction)
        )


@rule
async def owner_of_request(owner_of: OwnerOf) -> HydratedOperator:
    request = OwnersRequest(sources=owner_of.files)
    owners = await Get(Owners, OwnersRequest, request)
    operator = owner_of.conjunction.get_operator(owners.addresses)
    return HydratedOperator(operator)


@dataclass(frozen=True)
class ChangesSince(QueryParser):
    since: str
    dependees: DependeesOption
    conjunction: TargetSelectionConjunction

    function_name = 'since'

    @classmethod
    def parse_from_args(
        cls,
        since,
        dependees=DependeesOption.NONE,
        conjunction=TargetSelectionConjunction.union,
    ):
        return cls(
            since=str(since),
            dependees=DependeesOption(dependees),
            conjunction=TargetSelectionConjunction(conjunction),
        )


@rule
async def since_request(
        scm_wrapper: UncachedScmWrapper,
        since: ChangesSince,
) -> HydratedOperator:
    scm = scm_wrapper.scm
    changed_options = ChangedOptions(
        since=since.since,
        diffspec=None,
        dependees=since.dependees,
    )
    changed = await Get(ChangedAddresses, ChangedRequest(
        sources=tuple(changed_options.changed_files(scm=scm)),
        dependees=changed_options.dependees,
    ))
    operator = since.conjunction.get_operator(changed.addresses)
    return HydratedOperator(operator)


@dataclass(frozen=True)
class ChangesForDiffspec(QueryParser):
    diffspec: str
    dependees: DependeesOption
    conjunction: TargetSelectionConjunction

    function_name = "changes_for_diffspec"

    @classmethod
    def parse_from_args(
        cls,
        diffspec,
        dependees=DependeesOption.NONE,
        conjunction=TargetSelectionConjunction.union,
    ):
        return cls(
            diffspec=str(diffspec),
            dependees=DependeesOption(dependees),
            conjunction=TargetSelectionConjunction(conjunction),
        )


@rule
async def changes_for_diffspec_request(
    scm_wrapper: UncachedScmWrapper, changes_for_diffspec: ChangesForDiffspec,
) -> HydratedOperator:
    scm = scm_wrapper.scm
    changed_options = ChangedOptions(
        since=None,
        diffspec=changes_for_diffspec.diffspec,
        dependees=changes_for_diffspec.dependees,
    )
    changed = await Get(ChangedAddresses, ChangedRequest(
        sources=tuple(changed_options.changed_files(scm=scm)),
        dependees=changed_options.dependees,
    ))
    operator = changes_for_diffspec.conjunction.get_operator(changed.addresses)
    return HydratedOperator(operator)


@dataclass(frozen=True)
class FilterOperator(Operator):
    filter_func: Callable

    def as_hydration_request(self, hts: Tuple[HydratedTarget, ...]):
        return FilterOperands(filter_func=self.filter_func, hts=hts,)


@dataclass(frozen=True)
class FilterOperands(QueryOperation):
    filter_func: Callable
    hts: Tuple[HydratedTarget, ...]

    def apply_filter(self) -> Addresses:
        return Addresses(tuple(ht.adaptor.address for ht in self.hts if self.filter_func(ht)))


@rule
def filter_results(operands: FilterOperands) -> IntermediateResults:
    return IntermediateResults(operands.apply_filter())


@dataclass(frozen=True)
class TypeFilter(QueryParser):
    allowed_type_aliases: Tuple[str, ...]

    function_name = "type_filter"

    @classmethod
    def parse_from_args(cls, *allowed_type_aliases):
        return cls(allowed_type_aliases=tuple(allowed_type_aliases))

    def quick_operator(self):
        return FilterOperator(lambda ht: ht.adaptor.type_alias in self.allowed_type_aliases)


@rule
def filter_request(type_filter: TypeFilter) -> HydratedOperator:
    return HydratedOperator(type_filter.quick_operator())


_T = TypeVar("_T", bound=QueryParser)


@dataclass(frozen=True)
class KnownQueryExpressions:
    components: Dict[str, Type[_T]]


@rule
def known_query_expressions(union_membership: UnionMembership) -> KnownQueryExpressions:
    return KnownQueryExpressions(
        {
            union_member.function_name: union_member
            for union_member in union_membership[QueryParser]
        }
    )


@dataclass(frozen=True)
class QueryComponentWrapper(Generic[_T]):
    underlying: _T


@dataclass(frozen=True)
class AddressRegexFilter(QueryParser):
    regexes: Tuple[str, ...]

    function_name = "no_regex"

    @classmethod
    def parse_from_args(cls, *regexes):
        return cls(regexes=tuple(regexes))

    def quick_operator(self):
        return FilterOperator(
            lambda ht: not any(re.search(rx, ht.adaptor.address.spec) for rx in self.regexes)
        )


@rule
def address_regex_filter_results(op: AddressRegexFilter) -> HydratedOperator:
    return HydratedOperator(op.quick_operator())


@dataclass(frozen=True)
class TagRegexFilter(QueryParser):
    tag_regexes: Tuple[str, ...]

    function_name = "no_tag_regex"

    @classmethod
    def parse_from_args(cls, *tag_regexes):
        return cls(tag_regexes=tuple(tag_regexes))

    def quick_operator(self):
        return FilterOperator(
            lambda t: not any(
                re.search(rx, tag) for rx in self.tag_regexes for tag in getattr(t, "tags", ())
            )
        )


@rule
def tag_regex_filter_results(op: TagRegexFilter) -> HydratedOperator:
    return HydratedOperator(op.quick_operator())


class Noop(QueryParser):

    function_name = "noop"

    @classmethod
    def parse_from_args(cls):
        return cls()

    def get_noop_operator(self):
        return NoopOperator()


class NoopOperator(Operator):
    def quick_hydrate_with_input(self, addresses: Addresses):
        return NoopOperands(addresses)


@rule
def hydrate_noop(noop: Noop) -> HydratedOperator:
    return HydratedOperator(noop.get_noop_operator())


@dataclass(frozen=True)
class NoopOperands(QueryOperation):
    addresses: Addresses


@rule
def noop_results(noop_operands: NoopOperands) -> IntermediateResults:
    return IntermediateResults(noop_operands.addresses)


@dataclass(frozen=True)
class UnionOperator(Operator):
    to_union: Addresses

    def quick_hydrate_with_input(self, addresses: Addresses):
        return UnionOperands(lhs=self.to_union, rhs=addresses)


@dataclass(frozen=True)
class UnionOperands(QueryOperation):
    lhs: Addresses
    rhs: Addresses

    def apply_union(self) -> Addresses:
        lhs = OrderedSet(self.lhs)
        rhs = OrderedSet(self.rhs)
        return Addresses(tuple(lhs | rhs))


@rule
def union_results(operands: UnionOperands) -> IntermediateResults:
    unioned_addresses = operands.apply_union()
    return IntermediateResults(unioned_addresses)


@dataclass(frozen=True)
class GetOperandsRequest:
    op: Operator
    addresses: Addresses


@dataclass(frozen=True)
class WrappedOperands:
    operands: QueryOperation


@dataclass(frozen=True)
class IntersectionOperator(Operator):
    to_intersect: Addresses

    def quick_hydrate_with_input(self, addresses: Addresses):
        return IntersectionOperands(lhs=self.to_intersect, rhs=addresses)


@rule
async def hydrate_operands(req: GetOperandsRequest) -> WrappedOperands:
    maybe_quick_operands = req.op.quick_hydrate_with_input(req.addresses)
    if maybe_quick_operands is not None:
        return WrappedOperands(maybe_quick_operands)

    thts = await Get(TransitiveHydratedTargets, Addresses, req.addresses)
    orig_addresses = frozenset(req.addresses)
    hts_within_original_set = [ht for ht in thts.closure if ht.adaptor.address in orig_addresses]
    logger.debug(f"len(hts)={len(hts_within_original_set)}, len(addrs)={len(orig_addresses)}")
    operands = req.op.as_hydration_request(tuple(hts_within_original_set))
    assert operands is not None
    return WrappedOperands(operands)


@dataclass(frozen=True)
class IntersectionOperands(QueryOperation):
    lhs: Addresses
    rhs: Addresses

    def apply_intersect(self) -> Addresses:
        lhs = OrderedSet(self.lhs)
        rhs = OrderedSet(self.rhs)
        return Addresses(tuple(lhs & rhs))


@rule
def intersect_results(intersection_operands: IntersectionOperands) -> IntermediateResults:
    intersected_addresses = intersection_operands.apply_intersect()
    return IntermediateResults(intersected_addresses)


class Minimize(QueryParser):

    function_name = "minimize"

    @classmethod
    def parse_from_args(cls):
        return cls()

    def __repr__(self):
        return "Minimize()"


@rule
def minimize_operation(op: Minimize) -> HydratedOperator:
    return HydratedOperator(MinimizeOperator())


class MinimizeOperator(Operator):
    def quick_hydrate_with_input(self, addresses: Addresses):
        return MinimizeOperands(addresses)


@dataclass(frozen=True)
class MinimizeOperands(QueryOperation):
    input_addresses: Addresses


@rule
async def minimize_results(operands: MinimizeOperands) -> IntermediateResults:
    hts = await Get(HydratedTargets, Addresses, operands.input_addresses)
    dep_roots = OrderedSet(dep_address for ht in hts for dep_address in ht.adaptor.dependencies)
    thts_internal = await Get(TransitiveHydratedTargets, Addresses(tuple(dep_roots)))
    internal_deps = frozenset(ht.adaptor.address for ht in thts_internal.closure)

    minimal_cover: OrderedSet[Address] = OrderedSet()
    for address in operands.input_addresses:
        if address not in internal_deps and address not in minimal_cover:
            minimal_cover.add(address)

    return IntermediateResults(Addresses(tuple(minimal_cover)))


@dataclass(frozen=True)
class QueryPipeline:
    query_components: Tuple[QueryParser, ...]


@dataclass(frozen=True)
class QueryPipelineRequest:
    pipeline: QueryPipeline
    input_addresses: Addresses


@rule
async def process_query_pipeline(query_pipeline_request: QueryPipelineRequest) -> QueryAddresses:
    query_pipeline = query_pipeline_request.pipeline
    addresses = query_pipeline_request.input_addresses
    logger.debug(f"initial addresses: {addresses}")
    for op_req in query_pipeline.query_components:
        logger.debug(f"op_req: {op_req}")
        hydrated_operator = await Get(HydratedOperator, QueryParser, op_req)
        logger.debug(f"cur addresses: {addresses}")
        wrapped_operands = await Get(WrappedOperands,
            GetOperandsRequest(op=hydrated_operator.operator, addresses=addresses,)
        )
        logger.debug(f"wrapped_operands: {wrapped_operands}")
        results = await Get(IntermediateResults, QueryOperation, wrapped_operands.operands)
        addresses = results.addresses
    logger.debug(f"query pipeline result: {addresses}")
    return QueryAddresses(addresses)


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
        raise QueryParseError(f"Error parsing query expression: {e}") from e

    if not isinstance(query_expression, ast.Call):
        type_name = type(query_expression).__name__
        raise QueryParseError(
            f"Query expression must be a single function call, but received {type_name}: "
            f"{ast.dump(query_expression)}."
        )

    func_expr = query_expression.func
    if not isinstance(func_expr, ast.Name):
        raise QueryParseError(
            "Function call in query expression should just be a name, but "
            f"received {type(func_expr).__name__}: {ast.dump(func_expr)}."
        )
    function_name = func_expr.id

    positional_args = [_parse_python_arg(x) for x in query_expression.args]
    keyword_args = {k.arg: _parse_python_arg(k.value) for k in query_expression.keywords}

    return ParsedPythonesqueFunctionCall(
        function_name=function_name, positional_args=positional_args, keyword_args=keyword_args,
    )


@dataclass(frozen=True)
class QueryParseInput:
    expr: str


class QueryParseError(Exception):
    pass


# FIXME: allow returning an @union!!!
@rule
def parse_query_expr(s: QueryParseInput, known: KnownQueryExpressions) -> QueryComponentWrapper:
    """Parse the input string and attempt to find a query function matching the function call.

    :return: A query component which can be resolved into `QueryAddresses` in the v2 engine.
    """
    try:
        parsed_function_call = _parse_python_esque_function_call(s.expr)
    except Exception as e:
        raise QueryParseError(f"Error parsing expression {s}: {e}.") from e

    name = parsed_function_call.function_name
    args = parsed_function_call.positional_args
    kwargs = parsed_function_call.keyword_args

    selected_function = known.components.get(name, None)
    if selected_function:
        query_component = selected_function.parse_from_args(*args, **kwargs)
        logger.debug(f"query_component: {query_component}, args: {args}, kwargs: {kwargs}")
        return QueryComponentWrapper(query_component)
    else:
        raise QueryParseError(
            f"Query function with name {name} not found (in expr {s})! The known functions are: {known}."
        )


def rules():
    return [
        RootRule(ChangesForDiffspec),
        RootRule(ChangesSince),
        RootRule(FilterOperands),
        RootRule(GetOperandsRequest),
        RootRule(IntersectionOperands),
        RootRule(Noop),
        RootRule(NoopOperands),
        RootRule(OwnerOf),
        RootRule(QueryParseInput),
        RootRule(QueryPipelineRequest),
        RootRule(Minimize),
        RootRule(MinimizeOperands),
        RootRule(UnionOperands),
        RootRule(AddressRegexFilter),
        RootRule(TagRegexFilter),
        RootRule(TypeFilter),
        UnionRule(Operator, FilterOperator),
        UnionRule(Operator, IntersectionOperator),
        UnionRule(Operator, NoopOperator),
        UnionRule(Operator, UnionOperator),
        UnionRule(OperatorRequest, ChangesForDiffspec),
        UnionRule(OperatorRequest, ChangesSince),
        UnionRule(OperatorRequest, Noop),
        UnionRule(OperatorRequest, OwnerOf),
        UnionRule(QueryOperation, FilterOperands),
        UnionRule(QueryOperation, IntersectionOperands),
        UnionRule(QueryOperation, NoopOperands),
        UnionRule(QueryOperation, UnionOperands),
        UnionRule(QueryOperation, MinimizeOperands),
        UnionRule(QueryParser, AddressRegexFilter),
        UnionRule(QueryParser, ChangesForDiffspec),
        UnionRule(QueryParser, ChangesSince),
        UnionRule(QueryParser, Noop),
        UnionRule(QueryParser, OwnerOf),
        UnionRule(QueryParser, TagRegexFilter),
        UnionRule(QueryParser, Minimize),
        UnionRule(QueryParser, TypeFilter),
        address_regex_filter_results,
        changes_for_diffspec_request,
        since_request,
        filter_request,
        filter_results,
        hydrate_noop,
        hydrate_operands,
        intersect_results,
        known_query_expressions,
        noop_results,
        owner_of_request,
        since_request,
        changes_for_diffspec_request,
        parse_query_expr,
        process_query_pipeline,
        tag_regex_filter_results,
        union_results,
        minimize_results,
        minimize_operation,
    ]
