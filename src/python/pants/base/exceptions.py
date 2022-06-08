# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from pants.util.strutil import bullet_list, softwrap

if TYPE_CHECKING:
    from pants.build_graph.address import Address


class TargetDefinitionException(Exception):
    """Indicates an invalid target definition.

    :API: public
    """

    def __init__(self, target, msg):
        """
        :param target: the target in question
        :param string msg: a description of the target misconfiguration
        """
        super().__init__(f"Invalid target {target}: {msg}")


class BuildConfigurationError(Exception):
    """Indicates an error in a pants installation's configuration."""


class BackendConfigurationError(BuildConfigurationError):
    """Indicates a plugin backend with a missing or malformed register module."""


class MappingError(Exception):
    """Indicates an error mapping addressable objects."""


class ResolveError(MappingError):
    """Indicates an error resolving targets."""

    @classmethod
    def did_you_mean(
        cls,
        bad_address: Address,
        *,
        description_of_origin: str,
        known_names: Iterable[str],
        namespace: str,
    ) -> ResolveError:
        return cls(
            softwrap(
                f"""
                The address {bad_address} from {description_of_origin} does not exist.

                The target name ':{bad_address.target_name}' is not defined in the directory
                {namespace}. Did you mean one of these target names?\n
                """
                + bullet_list(f":{name}" for name in known_names)
            )
        )
