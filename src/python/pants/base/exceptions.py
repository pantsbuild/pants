# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable


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
        cls, *, bad_name: str, known_names: Iterable[str], namespace: str
    ) -> "ResolveError":
        possibilities = "\n  ".join(f":{target_name}" for target_name in sorted(known_names))
        return cls(
            f"'{bad_name}' was not found in namespace '{namespace}'. Did you mean one "
            f"of:\n  {possibilities}"
        )
