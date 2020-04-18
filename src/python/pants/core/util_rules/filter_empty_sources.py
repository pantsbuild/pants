# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import TypeVar

from typing_extensions import Protocol

from pants.engine.objects import Collection
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import HydratedSources, HydrateSourcesRequest
from pants.engine.target import Sources as SourcesField
from pants.engine.target import Target
from pants.engine.target import rules as target_rules


# This protocol allows us to work with any arbitrary Configuration. See
# https://mypy.readthedocs.io/en/stable/protocols.html.
class ConfigurationWithSources(Protocol):
    @property
    def sources(self) -> SourcesField:
        ...


C = TypeVar("C", bound=ConfigurationWithSources)


class ConfigurationsWithSources(Collection[C]):
    """Configurations which have non-empty source fields."""


class ConfigurationsWithSourcesRequest(Collection[C]):
    """Request to filter out all configs with empty source fields.

    This works with any Configurations, so long as they have a `sources` field defined.
    """


@rule
async def determine_configurations_with_sources(
    request: ConfigurationsWithSourcesRequest,
) -> ConfigurationsWithSources:
    all_sources = await MultiGet(
        Get[HydratedSources](HydrateSourcesRequest, config.sources.request) for config in request
    )
    return ConfigurationsWithSources(
        config for config, sources in zip(request, all_sources) if sources.snapshot.files
    )


class TargetsWithSources(Collection[Target]):
    """Targets which have non-empty source fields."""


class TargetsWithSourcesRequest(Collection[Target]):
    """Request to filter out all targets with empty source fields."""


@rule
async def determine_targets_with_sources(request: TargetsWithSourcesRequest) -> TargetsWithSources:
    all_sources = await MultiGet(
        Get[HydratedSources](HydrateSourcesRequest, tgt.get(SourcesField).request)
        for tgt in request
    )
    return TargetsWithSources(
        tgt for tgt, sources in zip(request, all_sources) if sources.snapshot.files
    )


def rules():
    return [
        determine_configurations_with_sources,
        determine_targets_with_sources,
        RootRule(ConfigurationsWithSourcesRequest),
        RootRule(TargetsWithSourcesRequest),
        *target_rules(),
    ]
