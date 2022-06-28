# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pants.engine.internals.native_engine import PyFailure


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


class NativeEngineFailure(Exception):
    """A wrapper around a `Failure` instance.

    TODO: This type is defined in Python because pyo3 doesn't support declaring Exceptions with
    additional fields. See https://github.com/PyO3/pyo3/issues/295
    """

    def __init__(self, msg: str, failure: PyFailure) -> None:
        super().__init__(msg)
        self.failure = failure
