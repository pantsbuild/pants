# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Contains the "base" code for plugin APIs which require partitioning."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from enum import Enum
from typing import Generic, Iterable, TypeVar

from typing_extensions import Protocol

from pants.core.goals.multi_tool_goal_helper import SkippableSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    FieldSet,
    SourcesField,
    SourcesPaths,
    SourcesPathsRequest,
    _get_field_set_fields,
)
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized
from pants.util.meta import frozen_after_init, runtime_ignore_subscripts

_FieldSetT = TypeVar("_FieldSetT", bound=FieldSet)


class PartitionerType(Enum):
    """What type of partitioner to use to partition the input specs."""

    CUSTOM = "custom"
    """The plugin author has a rule to go from `RequestType.PartitionRequest` -> `Partitions`."""

    DEFAULT_SINGLE_PARTITION = "default_single_partition"
    """Registers a partitioner which returns the inputs as a single partition."""


class PartitionKey(Protocol):
    @property
    def description(self) -> str:
        ...


PartitionKeyT = TypeVar("PartitionKeyT", bound=PartitionKey)
PartitionElementT = TypeVar("PartitionElementT")


@runtime_ignore_subscripts
class Partitions(FrozenDict["PartitionKeyT", "tuple[PartitionElementT, ...]"]):
    """A mapping from <partition key> to <partition>.

    When implementing a plugin, one of your rules will return this type, taking in a
    `PartitionRequest` specific to your plugin.

    The return likely will fit into one of:
        - Returning an empty partition: E.g. if your tool is being skipped.
        - Returning one partition. The partition may contain all of the inputs
            (as will likely be the case for target-based plugins) or a subset (which will likely be the
            case for targetless plugins).
        - Returning >1 partition. This might be the case if you can't run
            the tool on all the inputs at once. E.g. having to run a Python tool on XYZ with Py3,
            and files ABC with Py2.

    The partition key can be of any type able to cross a rule-boundary, and will be provided to the
    rule which "runs" your tool. If it isn't `None` it should implement the `PartitionKey` protocol.

    NOTE: The partition may be divided further into multiple batches.
    """

    @classmethod
    def single_partition(
        cls, elements: Iterable[PartitionElementT], key: PartitionKeyT = None  # type: ignore[assignment]
    ) -> Partitions[PartitionKeyT, PartitionElementT]:
        """Helper constructor for implementations that have only one partition."""
        return Partitions([(key, tuple(elements))])


# NB: Not frozen so it can be subclassed
@frozen_after_init
@dataclass(unsafe_hash=True)
@runtime_ignore_subscripts
class _BatchBase(Generic[PartitionKeyT, PartitionElementT]):
    """Base class for a collection of elements that should all be processed together.

    For example, a collection of strings pointing to files that should be linted in one process, or
    a collection of field-sets pointing at tests that should all execute in the same process.
    """

    tool_name: str
    elements: tuple[PartitionElementT, ...]
    partition_key: PartitionKeyT


@dataclass(frozen=True)
@runtime_ignore_subscripts
class _PartitionFieldSetsRequestBase(Generic[_FieldSetT]):
    """Returns a unique type per calling type.

    This serves us 2 purposes:
        1. `<Core Defined Plugin Type>.PartitionRequest` is the unique type used as a union base for plugin registration.
        2. `<Plugin Defined Subclass>.PartitionRequest` is the unique type used as the union member.
    """

    field_sets: tuple[_FieldSetT, ...]


@dataclass(frozen=True)
class _PartitionFilesRequestBase:
    """Returns a unique type per calling type.

    This serves us 2 purposes:
        1. `<Core Defined Plugin Type>.PartitionRequest` is the unique type used as a union base for plugin registration.
        2. `<Plugin Defined Subclass>.PartitionRequest` is the unique type used as the union member.
    """

    files: tuple[str, ...]


@memoized
def _single_partition_field_sets_partitioner_rules(cls) -> Iterable:
    """Returns a rule that implements a "partitioner" for `PartitionFieldSetsRequest`, which returns
    one partition."""

    @rule(
        _param_type_overrides={
            "request": cls.PartitionRequest,
            "subsystem": cls.tool_subsystem,
        }
    )
    async def partitioner(
        request: _PartitionFieldSetsRequestBase, subsystem: SkippableSubsystem
    ) -> Partitions:
        return Partitions() if subsystem.skip else Partitions.single_partition(request.field_sets)

    return collect_rules(locals())


@memoized
def _single_partition_field_sets_by_file_partitioner_rules(cls) -> Iterable:
    """Returns a rule that implements a "partitioner" for `PartitionFieldSetsRequest`, which returns
    one partition."""

    # NB: This only works if the FieldSet has a single `SourcesField` field. We check here for
    # a better user experience.
    sources_field_name = None
    for fieldname, fieldtype in _get_field_set_fields(cls.field_set_type).items():
        if issubclass(fieldtype, SourcesField):
            if sources_field_name is None:
                sources_field_name = fieldname
                break
            raise TypeError(
                f"Type {cls.field_set_type} has multiple `SourcesField` fields."
                + " Pants can't provide a default partitioner."
            )
    else:
        raise TypeError(
            f"Type {cls.field_set_type} has does not have a `SourcesField` field."
            + " Pants can't provide a default partitioner."
        )

    @rule(
        _param_type_overrides={
            "request": cls.PartitionRequest,
            "subsystem": cls.tool_subsystem,
        }
    )
    async def partitioner(
        request: _PartitionFieldSetsRequestBase, subsystem: SkippableSubsystem
    ) -> Partitions:
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
