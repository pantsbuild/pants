# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Generic, Iterable, Tuple, TypeVar

from typing_extensions import Protocol

from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import HydratedSources, HydrateSourcesRequest
from pants.engine.target import Sources as SourcesField
from pants.engine.target import rules as target_rules
from pants.util.meta import frozen_after_init


# This protocol allows us to work with any arbitrary Configuration. See
# https://mypy.readthedocs.io/en/stable/protocols.html.
class ConfigurationWithSources(Protocol):
    @property
    def sources(self) -> SourcesField:
        ...


C = TypeVar("C", bound=ConfigurationWithSources)


@dataclass(frozen=True)
class ConfigurationsWithSources(Generic[C]):
    """Configurations which have non-empty source fields."""

    configs: Tuple[C, ...]


@frozen_after_init
@dataclass(unsafe_hash=True)
class ConfigurationsWithSourcesRequest(Generic[C]):
    """Request to filter out all configs with empty source fields.

    This works with any Configurations, so long as they have a `sources` field defined.
    """

    configs: Tuple[C, ...]

    def __init__(self, configs: Iterable[C]) -> None:
        self.configs = tuple(configs)


@rule
async def determine_configurations_with_sources(
    request: ConfigurationsWithSourcesRequest,
) -> ConfigurationsWithSources:
    all_sources = await MultiGet(
        Get[HydratedSources](HydrateSourcesRequest, config.sources.request)
        for config in request.configs
    )
    return ConfigurationsWithSources(
        tuple(
            config
            for config, sources in zip(request.configs, all_sources)
            if sources.snapshot.files
        )
    )


def rules():
    return [
        determine_configurations_with_sources,
        *target_rules(),
        RootRule(ConfigurationsWithSourcesRequest),
    ]
