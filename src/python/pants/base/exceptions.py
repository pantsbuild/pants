# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.exiter import PANTS_FAILED_EXIT_CODE


class TaskError(Exception):
    """Indicates a task has failed.

    :API: public
    """

    def __init__(self, *args, **kwargs):
        """
        :param int exit_code: an optional exit code (defaults to nonzero)
        :param list failed_targets: an optional list of failed targets (default=[])
        """
        self._exit_code: int = kwargs.pop("exit_code", PANTS_FAILED_EXIT_CODE)
        self._failed_targets = kwargs.pop("failed_targets", [])
        super().__init__(*args, **kwargs)

    @property
    def exit_code(self) -> int:
        return self._exit_code

    @property
    def failed_targets(self):
        return self._failed_targets


class ErrorWhileTesting(TaskError):
    """Raised when an actual test run failed.

    This is used to distinguish test run failures from infrastructure failures.

    :API: public
    """


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


class IncompatiblePlatformsError(Exception):
    """Indicates that target platforms are incompatible with a target that contains native code."""


class MappingError(Exception):
    """Indicates an error mapping addressable objects."""


class UnaddressableObjectError(MappingError):
    """Indicates an un-addressable object was found at the top level."""


class DuplicateNameError(MappingError):
    """Indicates more than one top-level object was found with the same name."""


class ResolveError(MappingError):
    """Indicates an error resolving targets."""
