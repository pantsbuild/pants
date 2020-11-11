# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import TypeVar

from typing_extensions import Protocol

from pants.engine.collection import Collection
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest
from pants.engine.target import Sources as SourcesField
from pants.engine.target import Target


# This protocol allows us to work with any arbitrary FieldSet. See
# https://mypy.readthedocs.io/en/stable/protocols.html.
class FieldSetWithSources(Protocol):
    @property
    def sources(self) -> SourcesField:
        ...


_FS = TypeVar("_FS", bound=FieldSetWithSources)


class FieldSetsWithSources(Collection[_FS]):
    """Field sets which have non-empty source fields."""


class FieldSetsWithSourcesRequest(Collection[_FS]):
    """Request to filter out all field sets with empty source fields.

    This works with any FieldSet, so long as it has a `sources` field defined.
    """


@rule
async def determine_field_sets_with_sources(
    request: FieldSetsWithSourcesRequest,
) -> FieldSetsWithSources:
    all_sources = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(field_set.sources)) for field_set in request
    )
    return FieldSetsWithSources(
        field_set for field_set, sources in zip(request, all_sources) if sources.snapshot.files
    )


class TargetsWithSources(Collection[Target]):
    """Targets which have non-empty source fields."""


class TargetsWithSourcesRequest(Collection[Target]):
    """Request to filter out all targets with empty source fields."""


@rule
async def determine_targets_with_sources(request: TargetsWithSourcesRequest) -> TargetsWithSources:
    all_sources = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(tgt.get(SourcesField))) for tgt in request
    )
    return TargetsWithSources(
        tgt for tgt, sources in zip(request, all_sources) if sources.snapshot.files
    )


def rules():
    return collect_rules()
