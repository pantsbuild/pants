# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Contains the "base" code for plugin APIs which require partitioning."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from enum import Enum
from typing import Generic, Iterable, Protocol, TypeVar, overload

from pants.core.goals.multi_tool_goal_helper import SkippableSubsystem
from pants.engine.collection import Collection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, SourcesField, SourcesPaths, SourcesPathsRequest
from pants.util.memo import memoized
from pants.util.meta import runtime_ignore_subscripts

_FieldSetT = TypeVar("_FieldSetT", bound=FieldSet)


class PartitionerType(Enum):
    """What type of partitioner to use to partition the input specs."""

    CUSTOM = "custom"
    """The plugin author has a rule to go from `RequestType.PartitionRequest` -> `Partitions`."""

    DEFAULT_SINGLE_PARTITION = "default_single_partition"
    """Registers a partitioner which returns the inputs as a single partition.

    The returned partition will have no metadata.
    """

    DEFAULT_ONE_PARTITION_PER_INPUT = "default_one_partition_per_input"
    """Registers a partitioner which returns a single-element partition per input.

    Each of the returned partitions will have no metadata.
    """

    def default_rules(self, cls, *, by_file: bool) -> Iterable:
        """Return an iterable of rules defining the default partitioning logic for this
        `PartitionerType`.

        NOTE: Not all `PartitionerType`s have default logic, so this method can return an empty iterable.

        :param by_file: If `True`, rules returned from this method (if any) will compute partitions with
          `str`-type elements, where each `str` value is the path to the resolved source field. If `False`, rule will compute
          partitions with `FieldSet`-type elements.
        """
        if self == PartitionerType.CUSTOM:
            # No default rules.
            return
        elif self == PartitionerType.DEFAULT_SINGLE_PARTITION:
            rules_generator = (
                _single_partition_file_rules if by_file else _single_partition_field_set_rules
            )
            yield from rules_generator(cls)
        elif self == PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT:
            rules_generator = (
                _partition_per_input_file_rules if by_file else _partition_per_input_field_set_rules
            )
            yield from rules_generator(cls)
        else:
            raise NotImplementedError(f"Partitioner type {self} is missing default rules!")


class PartitionMetadata(Protocol):
    @property
    def description(self) -> str | None:
        ...


class _EmptyMetadata:
    @property
    def description(self) -> None:
        return None


PartitionMetadataT = TypeVar("PartitionMetadataT", bound=PartitionMetadata)
PartitionElementT = TypeVar("PartitionElementT")


@dataclass(frozen=True)
@runtime_ignore_subscripts
class Partition(Generic[PartitionElementT, PartitionMetadataT]):
    """A collection of 'compatible' inputs for a plugin tool, with optional common metadata.

    Inputs are 'compatible' if it is safe/possible for them to be processed in the same invocation
    of a tool (i.e. two files formatted in the same run of a formatter, or two test targets executed
    in a single test runner process).

    The metadata in a partition (if any) can be any type able to cross a rule boundary, and will be
    provided to the rule which "runs" your tool. If it isn't `None` it must implement the
    `PartitionMetadata` protocol.

    NOTE: Partitions may be further divided into multiple batches before being passed to the tool-running
    rule. When this happens, the same metadata is passed along with each batch.
    """

    elements: tuple[PartitionElementT, ...]
    metadata: PartitionMetadataT


@runtime_ignore_subscripts
class Partitions(Collection[Partition[PartitionElementT, PartitionMetadataT]]):
    """A collection of (<compatible inputs>, <metadata>) pairs.

    When implementing a plugin, one of your rules will return this type, taking in a
    `PartitionRequest` specific to your plugin.

    The return likely will fit into one of:
        - Returning empty partitions: E.g. if your tool is being skipped.
        - Returning one partition. The partition may contain all of the inputs
            (as will likely be the case for target-based plugins) or a subset (which will likely be the
            case for targetless plugins).
        - Returning >1 partition. This might be the case if you can't run
            the tool on all the inputs at once. E.g. having to run a Python tool on XYZ with Py3,
            and files ABC with Py2.
    """

    @overload
    @classmethod
    def single_partition(
        cls, elements: Iterable[PartitionElementT]
    ) -> Partitions[PartitionElementT, _EmptyMetadata]:
        ...

    @overload
    @classmethod
    def single_partition(
        cls, elements: Iterable[PartitionElementT], *, metadata: PartitionMetadataT
    ) -> Partitions[PartitionElementT, PartitionMetadataT]:
        ...

    @classmethod
    def single_partition(
        cls, elements: Iterable[PartitionElementT], *, metadata: PartitionMetadataT | None = None
    ) -> Partitions:
        """Helper constructor for implementations that have only one partition."""
        return Partitions([Partition(tuple(elements), metadata or _EmptyMetadata())])


@dataclass(frozen=True)
@runtime_ignore_subscripts
class _BatchBase(Generic[PartitionElementT, PartitionMetadataT], EngineAwareParameter):
    """Base class for a collection of elements that should all be processed together.

    For example, a collection of strings pointing to files that should be linted in one process, or
    a collection of field-sets pointing at tests that should all execute in the same process.
    """

    tool_name: str
    elements: tuple[PartitionElementT, ...]
    partition_metadata: PartitionMetadataT


@dataclass(frozen=True)
@runtime_ignore_subscripts
class _PartitionFieldSetsRequestBase(Generic[_FieldSetT], EngineAwareParameter):
    """Returns a unique type per calling type.

    This serves us 2 purposes:
        1. `<Core Defined Plugin Type>.PartitionRequest` is the unique type used as a union base for plugin registration.
        2. `<Plugin Defined Subclass>.PartitionRequest` is the unique type used as the union member.
    """

    field_sets: tuple[_FieldSetT, ...]


@dataclass(frozen=True)
class _PartitionFilesRequestBase(EngineAwareParameter):
    """Returns a unique type per calling type.

    This serves us 2 purposes:
        1. `<Core Defined Plugin Type>.PartitionRequest` is the unique type used as a union base for plugin registration.
        2. `<Plugin Defined Subclass>.PartitionRequest` is the unique type used as the union member.
    """

    files: tuple[str, ...]


@memoized
def _single_partition_field_set_rules(cls) -> Iterable:
    """Returns a rule that implements a "partitioner" for `PartitionFieldSetsRequest`, which returns
    one partition."""

    @rule(
        canonical_name_suffix=cls.__name__,
        _param_type_overrides={
            "request": cls.PartitionRequest,
            "subsystem": cls.tool_subsystem,
        },
    )
    async def partitioner(
        request: _PartitionFieldSetsRequestBase, subsystem: SkippableSubsystem
    ) -> Partitions[FieldSet, _EmptyMetadata]:
        return Partitions() if subsystem.skip else Partitions.single_partition(request.field_sets)

    return collect_rules(locals())


@memoized
def _single_partition_file_rules(cls) -> Iterable:
    """Returns a rule that implements a "partitioner" for `PartitionFieldSetsRequest`, which returns
    one partition."""

    # NB: This only works if the FieldSet has a single `SourcesField` field. We check here for
    # a better user experience.
    sources_field_name = _get_sources_field_name(cls.field_set_type)

    @rule(
        canonical_name_suffix=cls.__name__,
        _param_type_overrides={
            "request": cls.PartitionRequest,
            "subsystem": cls.tool_subsystem,
        },
    )
    async def partitioner(
        request: _PartitionFieldSetsRequestBase, subsystem: SkippableSubsystem
    ) -> Partitions[str, _EmptyMetadata]:
        assert sources_field_name is not None
        all_sources_paths = await MultiGet(
            Get(SourcesPaths, SourcesPathsRequest(getattr(field_set, sources_field_name)))
            for field_set in request.field_sets
        )

        return (
            Partitions()
            if subsystem.skip
            else Partitions.single_partition(
                itertools.chain.from_iterable(
                    sources_paths.files for sources_paths in all_sources_paths
                )
            )
        )

    return collect_rules(locals())


@memoized
def _partition_per_input_field_set_rules(cls) -> Iterable:
    """Returns a rule that implements a "partitioner" for `PartitionFieldSetsRequest`, which returns
    a single-element partition per input."""

    @rule(
        canonical_name_suffix=cls.__name__,
        _param_type_overrides={
            "request": cls.PartitionRequest,
            "subsystem": cls.tool_subsystem,
        },
    )
    async def partitioner(
        request: _PartitionFieldSetsRequestBase, subsystem: SkippableSubsystem
    ) -> Partitions[FieldSet, _EmptyMetadata]:
        return (
            Partitions()
            if subsystem.skip
            else Partitions(
                Partition((field_set,), _EmptyMetadata()) for field_set in request.field_sets
            )
        )

    return collect_rules(locals())


@memoized
def _partition_per_input_file_rules(cls) -> Iterable:
    """Returns a rule that implements a "partitioner" for `PartitionFieldSetsRequest`, which returns
    a single-element partition per input."""

    # NB: This only works if the FieldSet has a single `SourcesField` field. We check here for
    # a better user experience.
    sources_field_name = _get_sources_field_name(cls.field_set_type)

    @rule(
        canonical_name_suffix=cls.__name__,
        _param_type_overrides={
            "request": cls.PartitionRequest,
            "subsystem": cls.tool_subsystem,
        },
    )
    async def partitioner(
        request: _PartitionFieldSetsRequestBase, subsystem: SkippableSubsystem
    ) -> Partitions[str, _EmptyMetadata]:
        assert sources_field_name is not None
        all_sources_paths = await MultiGet(
            Get(SourcesPaths, SourcesPathsRequest(getattr(field_set, sources_field_name)))
            for field_set in request.field_sets
        )

        return (
            Partitions()
            if subsystem.skip
            else Partitions(
                Partition((path,), _EmptyMetadata())
                for path in itertools.chain.from_iterable(
                    sources_paths.files for sources_paths in all_sources_paths
                )
            )
        )

    return collect_rules(locals())


def _get_sources_field_name(field_set_type: type[FieldSet]) -> str:
    """Get the name of the one `SourcesField` belonging to the given target type.

    NOTE: The input target type's fields must contain exactly one `SourcesField`.
    Otherwise this method will raise a `TypeError`.
    """

    sources_field_name = None
    for fieldname, fieldtype in field_set_type.fields.items():
        if issubclass(fieldtype, SourcesField):
            if sources_field_name is None:
                sources_field_name = fieldname
                break
            raise TypeError(
                f"Type {field_set_type} has multiple `SourcesField` fields."
                + " Pants can't provide a default partitioner."
            )
    else:
        raise TypeError(
            f"Type {field_set_type} has does not have a `SourcesField` field."
            + " Pants can't provide a default partitioner."
        )
    return sources_field_name
