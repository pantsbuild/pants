# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


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


class UnaddressableObjectError(MappingError):
    """Indicates an un-addressable object was found at the top level."""


class DuplicateNameError(MappingError):
    """Indicates more than one top-level object was found with the same name."""


class ResolveError(MappingError):
    """Indicates an error resolving targets."""
